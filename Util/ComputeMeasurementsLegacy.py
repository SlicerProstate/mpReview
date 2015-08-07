import shutil, string, os, sys, glob, xml.dom.minidom, json
import SimpleITK as sitk

# Given the location of data and a JSON configuration file that has the following
# structure:
#
# Studies: <list>
# SeriesTypes: <list of canonical names>
# MeasurementTypes: <list of canonical names for the series>
# Readers: <list of reader IDs>
#
# find series that match the list (study and series type), compute all
# measurement types, for all labels, and save them at the Measurements level.

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
    try:
      seriesAttributes = json.loads(open(canonicalFile,'r').read())
    except:
      continue

    # check if the series type is of interest
    if not seriesAttributes['CanonicalType'] in settings['SeriesTypes']:
      continue
 
    if 1:
      # check if segmentation is available for this series
      segmentationsPath = os.path.join(studyDir,s,'Segmentations')
      
      for reader in settings['Readers']:
        segFiles = glob.glob(segmentationsPath+'/'+reader+'-2*')

        if not len(segFiles):
          continue
        segFiles.sort()

        # consider only the most recent seg file for the given reader
        segmentationFile = segFiles[-1]

        imageFile = os.path.join(studyDir,s,'Reconstructions',s+'.nrrd')

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
          print 'ERROR: Image/label sizes do not match!'
          abort()

        stats = sitk.LabelStatisticsImageFilter()
        stats.Execute(label,label)
        totalLabels = stats.GetNumberOfLabels()        
        if totalLabels<2:
          print segmentationFile
          print "ERROR: Segmentation should have exactly 2 labels!"
          continue

        allLabelIDs = list(stats.GetLabels())
        print allLabelIDs
        allLabelIDs.sort()

        for labelID in allLabelIDs[1:]:
          structure = str(labelID)
          measurements = {}
          measurements['SegmentationName'] = structure
 
          # threshold to label 1
          thresh = sitk.BinaryThresholdImageFilter()
          thresh.SetLowerThreshold(labelID)
          thresh.SetUpperThreshold(labelID)
          thresh.SetInsideValue(1)
          thresh.SetOutsideValue(0)
          thisLabel = thresh.Execute(label)

          stats.Execute(image,thisLabel)
 
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
              spacing = thisLabel.GetSpacing()
              measurements["Volume"] = stats.GetCount(1)*spacing[0]*spacing[1]*spacing[2]
            if mtype.startswith("Percentile"):
              npImage = sitk.GetArrayFromImage(image)
              npLabel = sitk.GetArrayFromImage(thisLabel)
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
          #print measurements
          f.write(json.dumps(measurements))
          f.close()

          #mm.recordMeasurement(study=c,series=s,struct=structure,reader=reader,mtype=mtype,mvalue=mvalue)
          #mvalue = mvalue+1

        #print str(measurements)

print 'WARNING: ADD RESAMPLING OF THE LABEL TO IMAGE!!!'
