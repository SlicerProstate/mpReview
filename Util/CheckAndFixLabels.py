import shutil, string, os, sys, glob, xml.dom.minidom, json
import SimpleITK as sitk
import logging

# Given the location of data and a JSON configuration file that has the following
# structure:
#
# Studies: <list>
# SeriesTypes: <list of canonical names>
# Structures: <list of canonical structure types>
# MeasurementTypes: <list of canonical names for the series>
# Readers: <list of reader IDs>
#
# Check the latest label that is available, if it is empty, find the most
# recent non-empty, if any, and check if the label dimensions match those of
# the image.

data = sys.argv[1]

settingsFile= sys.argv[2]

settingsData = open(settingsFile).read()
settings = json.loads(settingsData)

class MeasurementsManager:
  def __init__(self):
    self.measurementsContainer = {}

  def recordMeasurement(self,study,series,struct,reader,mtype,mvalue):
    mc = self.measurementsContainer
    if not study in mc.keys():
      mc[study] = {}
    if not series in mc[study].keys():
      mc[study][series] = {}
    if not struct in mc[study][series].keys(): 
      mc[study][series][struct] = {}
    if not reader in mc[study][series][struct].keys():
      mc[study][series][struct][reader] = {}
    #if not reader in mc[study][series][struct][mtype].keys:
    #  mc[study][series][struct][reader][mtype] = ''

    mc[study][series][struct][reader][mtype] = mvalue

  def getJSON(self):
    return json.dumps(self.measurementsContainer)

  def getCSV(self):
    return
    

def getElementValue(dom,name):
  elements = dom.getElementsByTagName('element')
  for e in elements:
    if e.getAttribute('name') == name:
      return e.childNodes[0].nodeValue

  return None

def checkTagExistence(dom,tag):
  elements = dom.getElementsByTagName('element')
  for e in elements:
    if e.getAttribute('tag') == tag:
      return True

  return False
 
def getValidDirs(dir):
  #dirs = [f for f in os.listdir(dir) if (not f.startswith('.')) and (not os.path.isfile(f))]
  dirs = os.listdir(dir)
  dirs = [f for f in dirs if os.path.isdir(dir+'/'+f)]
  dirs = [f for f in dirs if not f.startswith('.')]
  return dirs

def getCanonicalType(dom):
  import re
  desc = getElementValue(dom,'SeriesDescription')
  if re.search('[a-zA-Z]',desc) == None:
    return "sutract"
  elif re.search('AX',desc) and re.search('T2',desc):
    return "Axial T2"
  elif re.search('Apparent Diffusion',desc):
    # TODO: parse platform-specific b-values etc
    return 'ADC'
  elif re.search('Ax Dynamic',desc) or re.search('3D DCE',desc):
    return 'DCE'
  else:
    return "Unknown"

logger = logging.getLogger('checker')
ch = logging.StreamHandler()
ch.setLevel(logging.INFO)
logger.addHandler(ch)

# if there is a label number mismatch, change the label id
fixLabels = True

# delete files with empty labels
removeEmpty = False

# resample label to the image reference
resampleLabel = False

seriesDescription2Count = {}
seriesDescription2Type = {}

studies = getValidDirs(data)

# FYI: BWH study-specific
#series = [str(s) for s in range(1,31)]

totalSeries = 0
totalStudies = 0

mm = MeasurementsManager()
mvalue = 0

# read structure to label ID for consistency checking
colorFile = "../Resources/Colors/PCampReviewColors.csv"
import csv
name2labelNumber = {}
with open(colorFile,'rb') as csvfile:
  reader = csv.DictReader(csvfile,delimiter=',')
  for index,row in enumerate(reader):
    name2labelNumber[row['Label']] = int(row['Number'])

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
    seriesAttributes = json.loads(open(canonicalFile,'r').read())

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
        segFiles.reverse()

        mostRecentProblematic = False

        for segmentationFile in segFiles:
          errorCode = 0
          # consider only the most recent seg file for the given reader
  
          imageFile = os.path.join(studyDir,s,'Reconstructions',s+'.nrrd')

          #print 'Reading ',imageFile,segmentationFile

          label = sitk.ReadImage(str(segmentationFile))
          image = sitk.ReadImage(imageFile)

          stats = sitk.LabelStatisticsImageFilter()
          stats.Execute(label,label)
          totalLabels = stats.GetNumberOfLabels()
          labelID = stats.GetLabels()[-1]

          logger.info('Checking '+segmentationFile+' total labels: '+str(totalLabels))

          if image.GetSize()[2] != label.GetSize()[2]:
            logger.error('Image/label sizes do not match: '+segmentationFile)
            errorCode = 1

          if totalLabels==1:
            logger.error("Segmentation has only one label:"+str(labelID)+" for "+\
                segmentationFile)
            if removeEmpty:
              os.unlink(segmentationFile)
              logger.info('Removed empty '+segmentationFile)
            errorCode = 2

          if totalLabels>2:
            logger.error("Segmentation has more than 2 labels:"+segmentationFile)
            errorCode = 3

          if totalLabels==2 and name2labelNumber[structure] != labelID:
            logging.error("Label inconsistent: "+str(labelID)+\
            ", expected "+str(name2labelNumber[structure])+\
            " for "+structure+" in "+segmentationFile)
            if fixLabels:
              ff = sitk.ChangeLabelImageFilter()
              ff.SetChangeMap({labelID:name2labelNumber[structure]})
              newLabel = ff.Execute(label)
              stats.Execute(newLabel,newLabel)
              sitk.WriteImage(newLabel,str(segmentationFile),True)
              logger.info('Fixed up label overwritten '+segmentationFile)
            errorCode = 4

          if errorCode:
            if segmentationFile == segFiles[0]:
              mostRecentProblematic = True
            if segmentationFile == segFiles[-1]:
              logger.critical('No valid segmentation found for '+segmentationFile)
            continue
          
          if mostRecentProblematic:
            logger.info('Error recovered in '+segmentationFile)

          if resampleLabel:
            logger.info('Resampling')
            resample = sitk.ResampleImageFilter()
            resample.SetReferenceImage(image)
            resample.SetInterpolator(sitk.sitkNearestNeighbor)
            label = resample.Execute(label)
            sitk.WriteImage(label,str(segmentationFile),True)

          break
