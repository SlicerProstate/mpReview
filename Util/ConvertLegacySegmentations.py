import shutil, string, os, sys, glob, xml.dom.minidom, json
import SimpleITK as sitk

# Given the location of data, create segmentations that conform to the current
#  conventions of file names and content (i.e., change the file name and the
#  underlying label). This was prepared to handle older datasets created at BWH
#  that saved all labels in one file

def getValidDirs(dir):
  #dirs = [f for f in os.listdir(dir) if (not f.startswith('.')) and (not os.path.isfile(f))]
  dirs = os.listdir(dir)
  dirs = [f for f in dirs if os.path.isdir(dir+'/'+f)]
  dirs = [f for f in dirs if not f.startswith('.')]
  return dirs

def readColors(fileName):
  import csv
  labelToNameMap = {}
  with open(fileName, 'rb') as csvfile:
    reader = csv.DictReader(csvfile, delimiter=',')
    for index,row in enumerate(reader):
      structureName = row['Label']
      labelToNameMap[int(row['Number'])] = structureName
      #print 'Added',row['Number']
  return labelToNameMap

data = sys.argv[1]

#mapping = { 1:3, 2:8, 3:8 }
mapping = { 1:53 }

# replace with the location on your system
labelsFile = '/Users/fedorov/github/PCampReview/Resources/Colors/PCampReviewColors.csv'

labelToNameMap = readColors(labelsFile)

allStudies = getValidDirs(data)

# initialize this list if need to look only at certain studies
#studiesToConsider = ['PCAMPMRI-00730_20040422_1234','PCAMPMRI-00754_20040530_1401','PCAMPMRI-00763_20040616_1436','PCAMPMRI-00767_20040617_1130','PCAMPMRI-00801_20040121_1434','PCAMPMRI-00844_20040519_1140']

#studiesToConsider = ['PCAMPMRI-00813_20040822_1541','PCAMPMRI-00801_20040812_1226']
studiesToConsider = []

for c in allStudies:

  if len(studiesToConsider):
    if not c in studiesToConsider:
      continue

  studyDir = os.path.join(data,c,'RESOURCES')

  try:
    series = os.listdir(studyDir)
  except:
    continue

  for s in series:
    if s.startswith('.'):
      continue

    canonicalPath = os.path.join(studyDir,s,'Canonical')
    canonicalFile = os.path.join(canonicalPath,s+'.json')
    try:
      seriesAttributes = json.loads(open(canonicalFile,'r').read())
    except:
      print 'Failed to open',canonicalFile
      continue

    # check if the series type is of interest
    # modify this as needed for the type of series of your interest
    #if seriesAttributes['CanonicalType']!='ADC':
    #  continue

    segmentationsPath = os.path.join(studyDir,s,'Segmentations')
    segmentations = glob.glob(segmentationsPath+'/*nrrd')

    for seg in segmentations:
      print seg
      fileName = os.path.split(seg)[1]
      try:
        # parse reader and daatetime from legacy filename convention
        (reader,datetime) = str(fileName).split('-')
      except:
        continue

      # check if segmentation is available for this series
      label = sitk.ReadImage(seg)

      stats = sitk.LabelStatisticsImageFilter()
      stats.Execute(label,label)
      totalLabels = stats.GetNumberOfLabels()
      if totalLabels<2:
        # only background label is available
        continue

      for l in stats.GetLabels():
        if l == 0 or not l in mapping.keys():
          # skip background and all labels not defined by the mapping
          continue

        # reset the label color to the remapped label
        thresh = sitk.BinaryThresholdImageFilter()
        thresh.SetLowerThreshold(l)
        thresh.SetUpperThreshold(l)
        thresh.SetInsideValue(mapping[int(l)])
        thresh.SetOutsideValue(0)
        separatedLabel = thresh.Execute(label)

        newFileName = os.path.join(segmentationsPath,reader+'-'+labelToNameMap[mapping[int(l)]]+'-'+datetime+'.nrrd')
        sitk.WriteImage(separatedLabel,newFileName,True)
