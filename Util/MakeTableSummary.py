import shutil, string, os, sys, glob, xml.dom.minidom, json
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

data = sys.argv[1]

settingsFile= sys.argv[2]

settingsData = open(settingsFile).read()
settings = json.loads(settingsData)

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

mvalue = 0

# populate header during first pass
header = []
# keep adding table rows, each row is one pass over the outer loop
table = []

header = ["StudyID"]
headerInitialized = False

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

  tableRow = [c]

  totalStudies = totalStudies+1
  seriesPerStudy = 0

  for stype in settings['SeriesTypes']:
    print 'looking for SeriesType = ',stype
    stypeFound = False
    
    for s in series:
      if stypeFound:
        break

      if s.startswith('.'):
        # handle '.DS_store'
        continue

      canonicalPath = os.path.join(studyDir,s,'Canonical')
      canonicalFile = os.path.join(canonicalPath,s+'.json')
      seriesAttributes = json.loads(open(canonicalFile,'r').read())

      # check if the series type is of interest
      if stype != seriesAttributes['CanonicalType']:
        continue

      segmentationsPath = os.path.join(studyDir,s,'Segmentations')
      try:
        # no segmentations for this series
        if len(os.listdir(segmentationsPath))==0:
          continue
      except:
        # no Segmentations directory
        continue

      print 'Found: ',c,s,canonicalFile
      stypeFound = True

      canonicalType = seriesAttributes['CanonicalType']
  

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

      print 'Structures:'+str(allStructures)

      for structure in allStructures:
        # check if segmentation is available for this series
        
        for mtype in settings['MeasurementTypes']:

          measurementsDir = os.path.join(studyDir,s,'Measurements')
          measurementsFile = measurementsDir+'/'+s+'-'+structure+'-fionafennessy.json'

          try:
            mjson = json.loads(open(measurementsFile,'r').read())
          except:
            print 'Failed to open ',measurementsFile
            mjson = 'NA'

          if not headerInitialized:
            header.append(structure+'.'+stype+'.'+mtype)
          if mjson == 'NA':
            tableRow.append('NA')          
          else:
            if mtype == "Mean":
              tableRow.append(mjson["Mean"])
            if mtype == "Median":
              tableRow.append(mjson["Median"])
            if mtype == "StandardDeviation":
              tableRow.append(mjson["StandardDeviation"])
            if mtype == "Minimum":
              tableRow.append(mjson["Minimum"])
            if mtype == "Maximum":
              tableRow.append(mjson["Maximum"])
            if mtype == "Volume":
              tableRow.append(mjson["Volume"])
  print header
  headerInitialized = True

  if tableRow:
    if len(tableRow)!=len(header):
      abort()
    table.append(tableRow)

print table

from tabulate import tabulate
t = tabulate(table,headers=header,tablefmt="tsv")

f = open(sys.argv[3],'w')
f.write(t)
f.close()
