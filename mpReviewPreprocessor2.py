'''

First sort instances with dicomsort Using

dicomsort.py -k ~/dropbox_partners/ProstateQTI ~/Temp/QTI-sorted/%PatientID_%StudyDate_%StudyTime/RESOURCES/%SeriesNumber/DICOM/%SOPInstanceUID.dcm

Then run this script to generate volume reconstructions
'''

import os, shutil, sys, subprocess, logging, glob, tqdm
import nibabel

#logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("mpReviewPreprocessor2")


def main(argv):
  totalSeriesToProcess = 0
  for root, dirs, files in os.walk(argv[0]):
    resourceType = os.path.split(root)[1]
    if not resourceType == "DICOM":
      continue
    totalSeriesToProcess = totalSeriesToProcess+1

  progressBar = tqdm.tqdm(total=totalSeriesToProcess)

  failedSeries = []
  multivolumeSeries = []
  for root, dirs, files in os.walk(argv[0]):
    resourceType = os.path.split(root)[1]
    if not resourceType == "DICOM":
      continue

    logger.info("Processing "+root)
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
      logger.error("Volume reconstruction failed for "+root)
      failedSeries.append(root)

    # rename all dcm2niix-created nii files, since they are not readable by the defailt Slicer reader
    for niiFile in niiFiles:
      im = nibabel.load(niiFile)
      if len(im.shape) == 4:
        # move multivolume so that it is not recognized by the default mpReview loader
        logger.debug("Moving multivolume nifti: "+niiFile)
        shutil.move(niiFile, niiFile+".multivolume")
        multivolumeSeries.append(niiFile+".miltivolume")

    progressBar.update(1)

  progressBar.close()

  if len(failedSeries):
    with open("failed_series.readme", "w") as f:
      for fs in failedSeries:
        f.write(fs+"\n")

  if len(multivolumeSeries):
    with open("multivolume_series.readme", "w") as f:
      for fs in multivolumeSeries:
        f.write(fs+"\n")

  return

# one argument is input dir
if __name__ == "__main__":
  # check to confirm dcm2niix is in the path!
  if len(sys.argv) != 2:
    logger.error("Input directory not specified!")
  main(sys.argv[1:])
