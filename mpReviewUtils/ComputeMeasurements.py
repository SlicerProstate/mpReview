import shutil, string, os, sys, glob, xml.dom.minidom, json, logging, argparse
import SimpleITK as sitk

# Given the location of data and a JSON configuration file that has the following
# structure:
#
# Studies: <list>
# SeriesTypes: <list of canonical names>
# Structures: <list of canonical structure types>
# MeasurementTypes: <list of canonical names for the series>
# Readers: <list of reader IDs>
#
# find series that match the list (study and series type), compute all
# measurement types, and save them at the Measurements level.

logger = logging.getLogger("mpReviewUtil:ComputeMeasurements")

def main(argv):

  try:
    parser = argparse.ArgumentParser(description="mpReview preprocessor v2 (dcm2niix-based)")
    parser.add_argument("-i", "--input-folder", dest="input_folder", metavar="PATH",
                        required=True, help="Folder of input sorted DICOM files (is expected to follow mpReview input hierarchy, see https://github.com/SlicerProstate/mpReview")
    parser.add_argument("-s", "--settings", dest="settings_file",
                        required=True, help="Parameters JSON file to drive measurements extraction")
    parser.add_argument("-v", dest="verbose", help="Verbose output", action="store_true")
    parser.add_argument("-l", "--log-file", dest="log_file")
    args = parser.parse_args(argv)
  except Exception as e:
    logger.error("Failed with exception parsing command line arguments: "+str(e))
    return

  data = args.input_folder
  settingsFile = args.settings_file

  if args.log_file:
    #logging.basicConfig(filename=args.log_file,level=logging.DEBUG)
    handler = logging.FileHandler(args.log_file)
    handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)

  if args.verbose:
    logger.addHandler(logging.StreamHandler())

  with open(settingsFile) as settingsFile:
    settings = json.loads(settingsFile.read())

  def getValidDirs(dir):
    #dirs = [f for f in os.listdir(dir) if (not f.startswith('.')) and (not os.path.isfile(f))]
    dirs = os.listdir(dir)
    dirs = [f for f in dirs if os.path.isdir(dir+'/'+f)]
    dirs = [f for f in dirs if not f.startswith('.')]
    return dirs

  seriesDescription2Count = {}
  seriesDescription2Type = {}

  studies = getValidDirs(data)

  totalSeries = 0
  totalStudies = 0

  mvalue = 0

  # resample label to the image reference
  # should probably be done once during preprocessing
  resampleLabel = False

  for c in studies:

    try:
      if not c in settings['Studies']:
        continue
    except:
      # if Studies is not initialized, assume need to process all
      pass

    studyDir = os.path.join(data,c,'RESOURCES')

    try:
      series = os.listdir(studyDir)
    except:
      continue

    totalStudies = totalStudies+1
    seriesPerStudy = 0

    for s in series:
      if s.startswith('.'):
        # handle '.DS_store'
        continue

      canonicalPath = os.path.join(studyDir,s,'Canonical')
      canonicalFile = os.path.join(canonicalPath,s+'.json')
      try:
        seriesAttributes = json.loads(open(canonicalFile,'r').read())
      except:
        continue

      # check if the series type is of interest
      if not seriesAttributes['CanonicalType'] in settings['SeriesTypes']:
        continue

      # if no structures specified in the config file, consider all
      allStructures = None
      try:
        allStructures = settings['Structures']
      except:
        allStructures = ['WholeGland','PeripheralZone','TumorROI_PZ_1',
            'TumorROI_CGTZ_1',
            'BPHROI_1',
            'NormalROI_PZ_1',
            'NormalROI_CGTZ_1']

      for structure in allStructures:
        # check if segmentation is available for this series
        segmentationsPath = os.path.join(studyDir,s,'Segmentations')

        for reader in settings['Readers']:
          segFiles = glob.glob(segmentationsPath+'/'+reader+'-'+structure+'*')

          if not len(segFiles):
            continue
          segFiles.sort()

          # consider only the most recent seg file for the given reader
          segmentationFile = segFiles[-1]

          reconstructionsDir = os.path.join(studyDir,s,'Reconstructions')
          nrrdFiles = glob.glob(os.path.join(reconstructionsDir,"*.nrrd"))
          niftiFiles = glob.glob(os.path.join(reconstructionsDir,"*.nii.gz"))

          if len(nrrdFiles) and len(niftiFiles):
            logger.error(f"found both NIFTI and NRRD files - skipping series: {reconstructionsDir}")
            continue
          if len(nrrdFiles)>1 or len(niftiFiles)>1:
            logger.error(f"found more than one reconstruction - skipping series: {reconstructionsDir}")
            continue

          if len(nrrdFiles):
            imageFile = nrrdFiles[0]
          if len(niftiFiles):
            imageFile = niftiFiles[0]
          else:
            logger.error(f"no reconstructions found: {reconstructionsDir}")
            continue

          label = sitk.ReadImage(str(segmentationFile))
          image = sitk.ReadImage(imageFile)

          if resampleLabel:
            resample = sitk.ResampleImageFilter()
            resample.SetReferenceImage(image)
            resample.SetInterpolator(sitk.sitkNearestNeighbor)
            label = resample.Execute(label)

          image.SetDirection(label.GetDirection())
          image.SetSpacing(label.GetSpacing())
          image.SetOrigin(label.GetOrigin())

          if image.GetSize()[2] != label.GetSize()[2]:
            logger.error(f'Image/label sizes do not match {reconstructionsDir}')
            continue

          stats = sitk.LabelStatisticsImageFilter()
          stats.Execute(label,label)
          totalLabels = stats.GetNumberOfLabels()
          if totalLabels<2:
            logger.error(f"Segmentation should have exactly 2 labels: {reconstructionsDir}, {segmentationFile}")
            continue

          # threshold to label 1
          thresh = sitk.BinaryThresholdImageFilter()
          thresh.SetLowerThreshold(1)
          thresh.SetUpperThreshold(100)
          thresh.SetInsideValue(1)
          thresh.SetOutsideValue(0)
          label = thresh.Execute(label)

          stats.Execute(image,label)

          measurements = {}
          measurements['SegmentationName'] = segmentationFile.split('/')[-1]

          for mtype in settings['MeasurementTypes']:

            if mtype == "Mean":
              measurements["Mean"] = stats.GetMean(1)
            if mtype == "Median":
              measurements["Median"] = stats.GetMedian(1)
            if mtype == "StandardDeviation":
              measurements["StandardDeviation"] = stats.GetSigma(1)
            if mtype == "Minimum":
              measurements["Minimum"] = stats.GetMinimum(1)
            if mtype == "Maximum":
              measurements["Maximum"] = stats.GetMaximum(1)
            if mtype == "Volume":
              spacing = label.GetSpacing()
              measurements["Volume"] = stats.GetCount(1)*spacing[0]*spacing[1]*spacing[2]
            if mtype.startswith("Percentile"):
              npImage = sitk.GetArrayFromImage(image)
              npLabel = sitk.GetArrayFromImage(label)
              pixels = npImage[npLabel==1]
              pixels.sort()
              percent = float(mtype[10:])/100.
              measurements[mtype] = float(pixels[len(pixels)*percent])

          measurementsDir = os.path.join(studyDir,s,'Measurements')
          try:
            os.mkdir(measurementsDir)
          except:
            pass
          measurementsFile = os.path.join(measurementsDir,s+'-'+structure+'-'+reader+'.json')
          f = open(measurementsFile,'w')
          f.write(json.dumps(measurements))
          f.close()

          logger.info(studyDir+'/'+s)
          logger.info(json.dumps(measurements))

          # assert(False)
            #mm.recordMeasurement(study=c,series=s,struct=structure,reader=reader,mtype=mtype,mvalue=mvalue)
            #mvalue = mvalue+1

          #print str(measurements)

if __name__ == "__main__":

  # n = read4DNIfTI('/Users/fedorov/Downloads/9-3D_DCE/dce.nii')
  main(sys.argv[1:])
