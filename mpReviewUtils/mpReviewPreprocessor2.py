'''

First sort instances with dicomsort Using

dicomsort.py -k <input directory with DICOM data> <output directory for mpReview>/%PatientID_%StudyDate/RESOURCES/%SeriesNumber/DICOM/%SOPInstanceUID.dcm

Then run this script to generate volume reconstructions:

python mpReviewPreprocessor2.py -i <output directory for mpReview>

'''

import tqdm, nibabel # not included in Slicer

import os, shutil, sys, subprocess, logging, glob, argparse

#logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("mpReviewPreprocessor2")

def saveMultivolumeAsNRRD(niiFileName, nrrdFileName):
  scene = slicer.vtkMRMLScene()

  mvNode = slicer.vtkMRMLMultiVolumeNode()

  reader = vtk.vtkNIFTIImageReader()
  reader.SetFileName(niiFileName)
  reader.SetTimeAsVector(True)
  reader.Update()
  header = reader.GetNIFTIHeader()
  qFormMatrix = reader.GetQFormMatrix()
  if not qFormMatrix:
    logger.debug('Warning: %s does not have a QFormMatrix - using Identity')
    qFormMatrix = vtk.vtkMatrix4x4()
  spacing = reader.GetOutputDataObject(0).GetSpacing()
  timeSpacing = reader.GetTimeSpacing()
  nFrames = reader.GetTimeDimension()
  if header.GetIntentCode() != header.IntentTimeSeries:
    intentName = header.GetIntentName()
    if not intentName:
      intentName = 'Nothing'
    logger.debug('Warning: %s does not have TimeSeries intent, instead it has \"%s\"' % (niiFileName,intentName))
    logger.debug('Trying to read as TimeSeries anyway')
  units = header.GetXYZTUnits()

  # try to account for some of the unit options
  # (Note: no test data available but we hope these are right)
  if units & header.UnitsMSec == header.UnitsMSec:
    timeSpacing /= 1000.
  if units & header.UnitsUSec == header.UnitsUSec:
    timeSpacing /= 1000. / 1000.
  spaceScaling = 1.
  if units & header.UnitsMeter == header.UnitsMeter:
    spaceScaling *= 1000.
  if units & header.UnitsMicron == header.UnitsMicron:
    spaceScaling /= 1000.
  spacing = [e * spaceScaling for e in spacing]

  # create frame labels using the timing info from the file
  # but use the advanced info so user can specify offset and scale
  volumeLabels = vtk.vtkDoubleArray()
  volumeLabels.SetNumberOfTuples(nFrames)
  frameLabelsAttr = ''
  for i in range(nFrames):
    frameId = 1 + timeSpacing * i
    volumeLabels.SetComponent(i, 0, frameId)
    frameLabelsAttr += str(frameId)+','
  frameLabelsAttr = frameLabelsAttr[:-1]

  # spacing and origin are in the ijkToRAS, so clear them from image data
  imageChangeInformation = vtk.vtkImageChangeInformation()
  imageChangeInformation.SetInputConnection(reader.GetOutputPort())
  imageChangeInformation.SetOutputSpacing( 1, 1, 1 )
  imageChangeInformation.SetOutputOrigin( 0, 0, 0 )
  imageChangeInformation.Update()

  # QForm includes directions and origin, but not spacing so add that
  # here by multiplying by a diagonal matrix with the spacing
  scaleMatrix = vtk.vtkMatrix4x4()
  for diag in range(3):
    scaleMatrix.SetElement(diag, diag, spacing[diag])
  ijkToRAS = vtk.vtkMatrix4x4()
  ijkToRAS.DeepCopy(qFormMatrix)
  vtk.vtkMatrix4x4.Multiply4x4(ijkToRAS, scaleMatrix, ijkToRAS)
  mvNode.SetIJKToRASMatrix(ijkToRAS)
  # mvNode.SetAndObserveDisplayNodeID(mvDisplayNode.GetID())
  mvNode.SetAndObserveImageData(imageChangeInformation.GetOutputDataObject(0))
  mvNode.SetNumberOfFrames(nFrames)

  storageNode = slicer.vtkMRMLMultiVolumeStorageNode()

  # set the labels and other attributes, then display the volume
  mvNode.SetLabelArray(volumeLabels)
  mvNode.SetLabelName("Label")

  mvNode.SetAttribute('MultiVolume.FrameLabels',frameLabelsAttr)
  mvNode.SetAttribute('MultiVolume.NumberOfFrames',str(nFrames))
  mvNode.SetAttribute('MultiVolume.FrameIdentifyingDICOMTagName','')
  mvNode.SetAttribute('MultiVolume.FrameIdentifyingDICOMTagUnits','')

  mvNode.SetName(str(nFrames)+' frames NIfTI MultiVolume')
  #Helper.SetBgFgVolumes(mvNode.GetID(),None)

  scene.AddNode(mvNode)
  scene.AddNode(storageNode)
  mvNode.SetAndObserveStorageNodeID(storageNode.GetID())

  storageNode.SetFileName(nrrdFileName)
  storageNode.WriteData(mvNode)

def main(argv):

  try:
    parser = argparse.ArgumentParser(description="mpReview preprocessor v2 (dcm2niix-based)")
    parser.add_argument("-i", "--input-folder", dest="input_folder", metavar="PATH",
                        required=True, help="Folder of input sorted DICOM files (is expected to follow mpReview input hierarchy, see https://github.com/SlicerProstate/mpReview")
    parser.add_argument("-v", dest="verbose", help="Verbose output", action="store_true")
    parser.add_argument("-l", "--log-file", dest="log_file")
    args = parser.parse_args(argv)

  except Exception as e:
    logger.error("Failed with exception parsing command line arguments: "+str(e))
    return

  if args.verbose:
    logger.setLevel(logging.DEBUG)
  else:
    logger.setLevel(logging.INFO)

  if args.log_file:
    #logging.basicConfig(filename=args.log_file,level=logging.DEBUG)
    handler = logging.FileHandler(args.log_file)
    handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)

  totalSeriesToProcess = 0
  for root, dirs, files in os.walk(args.input_folder):
    resourceType = os.path.split(root)[1]
    if not resourceType == "DICOM":
      continue
    totalSeriesToProcess = totalSeriesToProcess+1

  progressBar = tqdm.tqdm(total=totalSeriesToProcess)

  failedSeries = []
  multivolumeSeries = []
  for root, dirs, files in os.walk(args.input_folder):
    resourceType = os.path.split(root)[1]
    if not resourceType == "DICOM":
      continue

    logger.debug("Processing "+root)
    reconstructionsDir = os.path.join(os.path.split(root)[0], "Reconstructions")
    if not os.path.exists(reconstructionsDir):
      os.mkdir(reconstructionsDir)
    converterCmd = ["dcm2niix", "-z", "y", "-o", reconstructionsDir, root]
    sp = subprocess.Popen(converterCmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (stdout, stderr) = sp.communicate()

    # check if nii and JSON files were created
    niiFiles = glob.glob(os.path.join(reconstructionsDir,"*.nii.gz"))
    jsonFiles = glob.glob(os.path.join(reconstructionsDir,"*.json"))
    if not len(niiFiles) or not len(jsonFiles):
      logger.debug("FAILED SERIES: "+root)

    # rename all dcm2niix-created nii files, since they are not readable by the defailt Slicer reader
    for niiFile in niiFiles:
      im = nibabel.load(niiFile)
      if len(im.shape) == 4:
        # make NRRD out of NIFTI multivolume
        nrrdFile = niiFile.split(".nii.gz")[0]+".nrrd"
        saveMultivolumeAsNRRD(niiFile, nrrdFile)

        # move multivolume so that it is not recognized by the default mpReview loader
        logger.debug("MULTIVOLUME SERIES: "+niiFile)
        shutil.move(niiFile, niiFile+".multivolume")

    progressBar.update(1)

    print("Processed %i of %i items" % (progressBar.n, progressBar.total))
  progressBar.close()

  sys.exit()
  return

# one argument is input dir
if __name__ == "__main__":

  # n = read4DNIfTI('/Users/fedorov/Downloads/9-3D_DCE/dce.nii')
  main(sys.argv[1:])
