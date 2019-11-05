# iterate over the reconstructions generated using dcm2niix
# find all reconstructions that have _Eq, and output a table formatted as follows:
#  PatientID; StudyDate; SeriesNumber; SeriesDescription
import os, sys, pydicom, glob, nibabel

dataDir = sys.argv[1]

incompleteSeries = []

studies = os.listdir(dataDir)

for c in studies:
  studyDir = os.path.join(dataDir,c,'RESOURCES')

  try:
    series = os.listdir(studyDir)
  except:
    continue

  for s in series:

    if s.startswith("."):
      continue

    reconstructionsDir = os.path.join(studyDir,s,'Reconstructions')
    dicomDir = os.path.join(studyDir,s,'DICOM')
    dicoms = glob.glob(os.path.join(dicomDir, "*.dcm"))
    oneDICOM = pydicom.read_file(dicoms[0])

    try:
      seriesNumber = oneDICOM.SeriesNumber
    except AttributeError:
      seriesNumber = "NA"
    try:
      seriesDescription = oneDICOM.SeriesDescription
    except AttributeError:
      seriesDescription = "NA"

    nReconstructions = 0
    for rName in os.listdir(reconstructionsDir):
      nReconstructions = nReconstructions+1

      [patient, date] = c.split("_")

      if rName.find("nii.gz")>0 and rName.find('_Eq')>0:
        #print(reconstructionsDir)
        incompleteSeries.append([patient, date, seriesNumber, seriesDescription, 'INCOMPLETE'])
      # filename can end in multivolume
      elif len(rName)-rName.find('.nii.gz')==7:
        nb = nibabel.load(os.path.join(reconstructionsDir, rName))
        if len(nb.header.get_data_dtype())!=0:
          incompleteSeries.append([patient, date, seriesNumber, seriesDescription, 'NOT SCALAR'])
    if nReconstructions==0:
      incompleteSeries.append([patient, date, seriesNumber, seriesDescription, 'NOT RECONSTRUCTED'])

with open(sys.argv[2], 'w') as f:
  f.write('PatientID;StudyDate;SeriesNumber;SeriesDescription;ProblemCode\n')
  for r in incompleteSeries:
    f.write(r[0]+';'+r[1]+';'+str(r[2])+';'+r[3]+';'+r[4]+'\n')