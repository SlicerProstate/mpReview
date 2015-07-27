import shutil, string, os, sys, glob, xml.dom.minidom
import datetime

# Iterate over all series in the directory that follows PCampReview convention,
# use rules defined in getCanonicalType() to 'tag' series according to the
# types of typical interest.
#
# Input argument: directory with the data

data = sys.argv[1]
#reader = sys.argv[2]
reader = 'fionafennessy'

def getValidDirs(dir):
  #dirs = [f for f in os.listdir(dir) if (not f.startswith('.')) and (not os.path.isfile(f))]
  dirs = os.listdir(dir)
  dirs = [f for f in dirs if os.path.isdir(dir+'/'+f)]
  dirs = [f for f in dirs if not f.startswith('.')]
  dirs = [f for f in dirs if not f.startswith('s')]
  return dirs

def getArteryROIs(segmentationsPath,reader):
  arteryRoiFile = {}
  arteries = ['RightArteryROI', 'LeftArteryROI']
  for artery in arteries:
    # check if segmentation is available for this series
    segFiles = glob.glob(segmentationsPath+'/'+reader+'-'+artery+'*')
    if not len(segFiles):
      arteryRoiFile[artery] = None
      continue
    segFiles.sort()
    segFiles.reverse()
    arteryRoiFile[artery] = os.path.join(segmentationsPath,segFiles[0])
  return arteryRoiFile

seriesDescription2Count = {}
seriesDescription2Type = {}

studies = getValidDirs(data)
totalSeries = 0
totalStudies = 0

binPath = '/xnat/fedorov/GE/bin/'
#OncoQuantVersion = '2015_0327'
OncoQuantVersion = '13.38.05'
OncoQuantExecutable = 'OncoQuantExec_' + OncoQuantVersion
OncoQuantExecutablePath = os.path.join(binPath,OncoQuantExecutable)
xmlConfigFilePath = '/xnat/mehrtash/OncoQuant_Nov2011_TwoParameter.xml' 
print os.path.isfile(xmlConfigFilePath)

studiesDictionary = {}
for c in studies:
  studyDir = os.path.join(data,c,'RESOURCES')

  try:
    series = os.listdir(studyDir)
  except:
    continue

  totalStudies = totalStudies+1
  seriesPerStudy = 0

  dic = {}
  for s in series:
    if not s.startswith('.'):
      canonicalPath = os.path.join(studyDir,s,'Canonical')
      f = open(os.path.join(canonicalPath,s+'.json'),'r')
      import json
      jsondata = json.load(f)
      f.close()
      if jsondata['CanonicalType']=='DCE' and c not in ['14','4','12','24']:
        oncoQuantDir = os.path.join(studyDir,s,'OncoQuant')
        dic['OncoQuantDir'] = oncoQuantDir
        dic['DCESeriesNumber'] = s
      if jsondata['CanonicalType']=='SUB':
        segmentationsDir = os.path.join(studyDir,s,'Segmentations')
        arteryRoiFile = getArteryROIs(segmentationsDir,reader)
        dic['arteryRoiFile'] = arteryRoiFile
  studiesDictionary[c] = dic
print studiesDictionary
for c in studies:
  print 'study:', c
for c in studies:
  print '-----------------------------------'
  print 'study:', c
  print '-----------------------------------'
  if 'OncoQuantDir' in studiesDictionary[c]:
    if os.path.exists(studiesDictionary[c]['OncoQuantDir']):
      oncoQuantDir = studiesDictionary[c]['OncoQuantDir']
      s = studiesDictionary[c]['DCESeriesNumber']
      nrrdFilePath = os.path.join(oncoQuantDir, s+ '.nrrd' )
      paramFilePath = os.path.join(oncoQuantDir, s+ '-parameters.txt' )
      print nrrdFilePath
      if os.path.isfile(nrrdFilePath) and os.path.isfile(paramFilePath):
        for aifChoice in ['Auto','Model','ManualLeftArteryROI', 'ManualRightArteryROI']:
          if aifChoice == 'Auto':
            aifChoiceNumber = '0'
            aifMap = ' '
          elif aifChoice == 'Model':
            aifChoiceNumber = '1'
          elif aifChoice == 'ManualLeftArteryROI':
            if segmentationsDir and arteryRoiFile['LeftArteryROI']:
            #if 'arteryRoiFile' in studiesDictionary[c]:
              aifChoiceNumber = '4'
              aifMapFilePath = studiesDictionary[c]['arteryRoiFile']['LeftArteryROI']
              aifMap = ' ' + aifMapFilePath + ' '
            else:
              break
          elif aifChoice == 'ManualRightArteryROI':
            if segmentationsDir and arteryRoiFile['RightArteryROI']:
              aifChoiceNumber = '4'
              aifMapFilePath = studiesDictionary[c]['arteryRoiFile']['RightArteryROI']
              aifMap = ' ' + aifMapFilePath + ' '
            else:
              break
          timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
          suffix = OncoQuantVersion + '-' + aifChoice + '-' +  timestamp 
          command = '(cd '+ oncoQuantDir +'; '+ OncoQuantExecutablePath +\
                    ' -d ' + nrrdFilePath +\
                    ' -q ' + paramFilePath +\
                    ' -s'+\
                    ' -aif '+ aifChoiceNumber + aifMap +\
                    '-o ' + suffix +\
                    ' -v ' + xmlConfigFilePath +\
                    ' -t |tee log_'+suffix+'.txt)'
          print command
          os.system(command)
      else:
        print 'nrrd or parameters file not available'
    else:
      print 'OncoQuant directory is not present'


