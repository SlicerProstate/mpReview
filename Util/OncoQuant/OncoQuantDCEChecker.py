import shutil, string, os, sys, glob, xml.dom.minidom

# Iterate over all series in the directory that follows PCampReview convention,
# use rules defined in getCanonicalType() to 'tag' series according to the
# types of typical interest.
#
# Input argument: directory with the data

data = sys.argv[1]

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

for c in studies:
  studyDir = os.path.join(data,c,'RESOURCES')

  try:
    series = os.listdir(studyDir)
  except:
    continue

  totalStudies = totalStudies+1
  seriesPerStudy = 0

  for s in series:
    if not s.startswith('.'):
      canonicalPath = os.path.join(studyDir,s,'Canonical')
      f = open(os.path.join(canonicalPath,s+'.json'),'r')
      import json
      jsondata = json.load(f)
      f.close()
      if jsondata['CanonicalType']=='DCE':
        print '--------------------------------------------------'
        print 'study: ', c,'series:',s
        oncoQuantDir = os.path.join(studyDir,s,'OncoQuant')
        if os.path.exists(oncoQuantDir):
          nrrdFilePath = os.path.join(oncoQuantDir, s+ '.nrrd' )
          paramFilePath = os.path.join(oncoQuantDir, s+ '-parameters.txt' )
          if os.path.isfile(nrrdFilePath):
            print 'nrrd size: ',os.stat(nrrdFilePath).st_size
          else:
            print 'nrrd file not available'
          if os.path.isfile(paramFilePath):
            print 'param size: ',os.stat(paramFilePath).st_size
          else:
            print 'param file not available'
        else:
          print 'OncoQuant directory is not present'


