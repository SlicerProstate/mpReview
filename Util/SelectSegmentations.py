import shutil, string, os, sys, glob, xml.dom.minidom, json

# Given the location of data, an output directory and a JSON configuration 
# file that has the following structure:
#
# Studies: <list>
# SeriesTypes: <list of canonical names>
# Structures: <list of canonical structure types>
# Readers: <list of reader IDs>
#
# find series that match the list (study and series type), select the latest
# segmentation for specified structure and reader, and copy that together with
# the volume reconstruction into the output directory

data = sys.argv[1]

settingsFile= sys.argv[2]

outputDir = sys.argv[3]

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

seriesDescription2Count = {}
seriesDescription2Type = {}

studies = getValidDirs(data)

totalSeries = 0
totalStudies = 0

mm = MeasurementsManager()
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

        # consider only the most recent seg file for the given reader
        segmentationFile = segFiles[-1]

        imageFile = os.path.join(studyDir,s,'Reconstructions',s+'.nrrd')

        destSegFileName = outputDir+'/'+c+'-'+s+'-'+seriesAttributes['CanonicalType']+'-'+structure+'-Seg.nrrd'
        destReconFileName = outputDir+'/'+c+'-'+s+'-'+seriesAttributes['CanonicalType']+'-Recon.nrrd'

        if os.path.exists(destSegFileName):
          print 'ERROR: file exists: ',destSegFileName
          continue

        shutil.copyfile(segmentationFile,destSegFileName)
        shutil.copyfile(imageFile,destReconFileName)

        print 'Copied',destSegFileName
        print 'Copied',destReconFileName

print 'WARNING: ADD RESAMPLING OF THE LABEL TO IMAGE!!!'
