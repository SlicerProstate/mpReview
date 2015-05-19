import os
import unittest
from __main__ import vtk, qt, ctk, slicer
from slicer.ScriptedLoadableModule import *
import argparse
import sys, shutil

#
# PCampReviewPreprocessor
#   Prepares the DICOM data to be compatible with PCampReview module
#

class PCampReviewPreprocessor(ScriptedLoadableModule):
  def __init__(self, parent):
    ScriptedLoadableModule.__init__(self, parent)
    parent.title = "PCampReview Preprocessor"
    parent.categories = ["Testing.PCampReview Tests"]
    parent.dependencies = []
    parent.contributors = ["Andrey Fedorov (BWH)"]
    parent.helpText = """
    This is a module for conditioning DICOM data for processing using PCampReview module
    """
    parent.acknowledgementText = """This module is based on the PCampReviewPreprocessor module that was originally developed by Csaba Pinter, PerkLab, Queen's University and was supported through the Applied Cancer Research Unit program of Cancer Care Ontario with funds provided by the Ontario Ministry of Health and Long-Term Care. This module was developed by Andrey Fedorov, BWH, and was supported by NIH via grants U24CA180918 and U01CA151261.""" # replace with organization, grant and thanks.
    self.parent = parent

    # Add this test to the SelfTest module's list for discovery when the module
    # is created.  Since this module may be discovered before SelfTests itself,
    # create the list if it doesn't already exist.
    try:
      slicer.selfTests
    except AttributeError:
      slicer.selfTests = {}
    slicer.selfTests['PCampReviewPreprocessor'] = self.runTest

  def runTest(self):
    tester = PCampReviewPreprocessorTest()
    tester.runTest()

#
# PCampReviewPreprocessorWidget
#

class PCampReviewPreprocessorWidget(ScriptedLoadableModuleWidget):
  def setup(self):
    self.developerMode = True
    ScriptedLoadableModuleWidget.setup(self)

    parametersCollapsibleButton = ctk.ctkCollapsibleButton()
    parametersCollapsibleButton.text = "Parameters"
    self.layout.addWidget(parametersCollapsibleButton)

    parametersFormLayout = qt.QFormLayout(parametersCollapsibleButton)

    self.inputDirButton = ctk.ctkDirectoryButton()
    parametersFormLayout.addRow("Input directory:",self.inputDirButton)

    self.outputDirButton = ctk.ctkDirectoryButton()
    parametersFormLayout.addRow("Output directory:",self.outputDirButton)

    self.copyDICOMButton = qt.QCheckBox()
    self.copyDICOMButton.setChecked(0)
    parametersFormLayout.addRow("Organize DICOMs:",self.copyDICOMButton)

    applyButton = qt.QPushButton('Run')
    parametersFormLayout.addRow(applyButton)

    applyButton.connect('clicked()',self.onRunClicked)

  def onRunClicked(self):
    logic = PCampReviewPreprocessorLogic()
    logic.Convert(self.inputDirButton.directory, self.outputDirButton.directory,
        copyDICOM=self.copyDICOMButton.checked)

#
# PCampReviewPreprocessorLogic
#

class PCampReviewPreprocessorLogic(ScriptedLoadableModuleLogic):
  """This class should implement all the actual 
  computation done by your module.  The interface 
  should be such that other python code can import
  this class and make use of the functionality without
  requiring an instance of the Widget
  """
  def __init__(self):
    ScriptedLoadableModuleLogic.__init__(self)

    self.dataDir = slicer.app.temporaryPath + '/PCampReviewPreprocessor'
    if os.access(self.dataDir, os.F_OK):
      import shutil
      shutil.rmtree(self.dataDir)
    
    os.mkdir(self.dataDir)

    self.dicomDatabaseDir = self.dataDir + '/CtkDicomDatabase'

  def Convert(self, inputDir, outputDir, copyDICOM):
    # inputDir = '/Users/fedorov/ImageData/QIICR/QIN PROSTATE/QIN-PROSTATE-01-0001/1.3.6.1.4.1.14519.5.2.1.3671.7001.133687106572018334063091507027'
    print('Database location: '+self.dicomDatabaseDir)
    print('FIXME: revert back to the original DB location when done!')
    self.OpenDatabase()
    print('Input directory: '+inputDir)
    self.ImportStudy(inputDir)

    print('Import completed, total '+str(len(slicer.dicomDatabase.patients()))+' patients imported')

    detailsPopup = slicer.modules.dicom.widgetRepresentation().self().detailsPopup
    for patient in slicer.dicomDatabase.patients():
      #print patient
      for study in slicer.dicomDatabase.studiesForPatient(patient):
        #print slicer.dicomDatabase.seriesForStudy(study)
        for series in [l for l in slicer.dicomDatabase.seriesForStudy(study)]:
          #print 'Series:',series
          #print seriesUIDs
          detailsPopup.offerLoadables([series], 'SeriesUIDList')
          detailsPopup.examineForLoading()

          #print detailsPopup.loadableTable.loadables
    
          # take the first one selected
          #for l in detailsPopup.loadableTable.loadables.values()[1:]:
          #  l.selected = False

          #loadables = [l for l in detailsPopup.loadableTable.loadables.values() if l.selected][0]
          #loadables = [l for l in detailsPopup.loadableTable.loadables.values()][0]

          seriesLoaded = False
          node = None
          for plugin in detailsPopup.loadablesByPlugin:
            for loadable in detailsPopup.loadablesByPlugin[plugin]:
              if loadable.selected:
                node = plugin.load(loadable)
                if node:
                  seriesLoaded = True
                  dcmFile = loadable.files[0]
                  seriesNumber = slicer.dicomDatabase.fileValue(loadable.files[0], "0020,0011")
                  patientID = slicer.dicomDatabase.fileValue(loadable.files[0], "0010,0020")
                  studyDate = slicer.dicomDatabase.fileValue(loadable.files[0], "0008,0020")
                  studyTime = slicer.dicomDatabase.fileValue(loadable.files[0], "0008,0030")[0:4]
              if seriesLoaded:
                break
            if seriesLoaded:
              break
        
          if node:
            storageNode = node.CreateDefaultStorageNode()
            import os
            studyID = patientID+'_'+studyDate+'_'+studyTime
            dirName = outputDir + '/'+studyID+'/RESOURCES/'+seriesNumber+'/Reconstructions/'
            xmlName = dirName+seriesNumber+'.xml'
            try:
              os.makedirs(dirName)
            except:
              pass
            os.system('dcm2xml '+dcmFile.replace(' ','\ ')+' > '+xmlName.replace(' ','\ '))
            nrrdName = dirName+seriesNumber+'.nrrd'
            #print(nrrdName)
            storageNode.SetFileName(nrrdName)
            storageNode.WriteData(node)

            # copy original DICOMs
            if copyDICOM:
              fileCount = 0
              dirName = outputDir + '/'+studyID+'/RESOURCES/'+seriesNumber+'/DICOM/'
              try:
                os.makedirs(dirName)
              except:
                pass
              for dcm in loadable.files:
                shutil.copy(dcm, dirName+'/'+ "%06d.dcm" % fileCount)
                fileCount = fileCount+1
          else:
            print 'No node!'

  def OpenDatabase(self):
    # Open test database and empty it
    if not os.access(self.dicomDatabaseDir, os.F_OK):
      os.mkdir(self.dicomDatabaseDir)

    dicomWidget = slicer.modules.dicom.widgetRepresentation().self()
    dicomWidget.onDatabaseDirectoryChanged(self.dicomDatabaseDir)

    slicer.dicomDatabase.initializeDatabase()

  def ImportStudy(self,dicomDataDir):
    indexer = ctk.ctkDICOMIndexer()

    # Import study to database
    indexer.addDirectory( slicer.dicomDatabase, dicomDataDir )
    indexer.waitForImportFinished()

  def LoadFirstPatientIntoSlicer(self):
    # Choose first patient from the patient list
    detailsPopup = slicer.modules.dicom.widgetRepresentation().self().detailsPopup
    patient = slicer.dicomDatabase.patients()[0]
    studies = slicer.dicomDatabase.studiesForPatient(patient)
    series = [slicer.dicomDatabase.seriesForStudy(study) for study in studies]
    seriesUIDs = [uid for uidList in series for uid in uidList]
    detailsPopup.offerLoadables(seriesUIDs, 'SeriesUIDList')
    detailsPopup.examineForLoading()

    loadables = detailsPopup.loadableTable.loadables

    # Load into Slicer
    detailsPopup = slicer.modules.dicom.widgetRepresentation().self().detailsPopup
    detailsPopup.loadCheckedLoadables()

def main(argv):
  try:
    # Parse command-line arguments
    parser = argparse.ArgumentParser(description="PCampReview preprocessor")
    parser.add_argument("-i", "--input-folder", dest="input_folder", metavar="PATH",
                        default="-", required=True, help="Folder of input DICOM files (can contain sub-folders)")
    parser.add_argument("-o", "--output-folder", dest="output_folder", metavar="PATH",
                        default=".", help="Folder to save converted datasets")
    parser.add_argument("-d","--copyDICOM",dest="copyDICOM",type=bool,default=False,
                        help="Organize DICOM files in the output directory")
    args = parser.parse_args(argv)

    # Check required arguments
    if args.input_folder == "-":
      print('Please specify input DICOM study folder!')
    if args.output_folder == ".":
      print('Current directory is selected as output folder (default). To change it, please specify --output-folder')

    logic = PCampReviewPreprocessorLogic()
    logic.Convert(args.input_folder,args.output_folder,copyDICOM=args.copyDICOM)

  except Exception, e:
    print e
  sys.exit()

if __name__ == "__main__":
  main(sys.argv[1:])
