import os
import unittest
from __main__ import vtk, qt, ctk, slicer
from slicer.ScriptedLoadableModule import *
import argparse
import sys

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

    applyButton = qt.QPushButton('Run')
    parametersFormLayout.addRow(applyButton)

    applyButton.connect('clicked()',self.onRunClicked)

  def onRunClicked(self):
    logic = PCampReviewPreprocessorLogic()
    logic.Convert(self.inputDirButton.directory, self.outputDirButton.directory)

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

  def Convert(self, inputDir, outputDir):
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
            # get path to dcmdump
            dcm2xml = '/Users/fedorov/local/bin/dcm2xml'
            storageNode = node.CreateDefaultStorageNode()
            import os
            studyID = patientID+'_'+studyDate+'_'+studyTime
            dirName = outputDir + '/'+studyID+'/RESOURCES/'+seriesNumber+'/Reconstructions/'
            xmlName = dirName+seriesNumber+'.xml'
            # WARNING: this expects presence of dcm2xml and is not portable AT ALL!!!
            try:
              os.makedirs(dirName)
            except:
              pass
            print('Running: dcm2xml '+dcmFile.replace(' ','\ ')+' > '+xmlName.replace(' ','\ '))
            os.system('/Users/fedorov/local/bin/dcm2xml '+dcmFile.replace(' ','\ ')+' > '+xmlName.replace(' ','\ '))
            nrrdName = dirName+seriesNumber+'.nrrd'
            print(nrrdName)
            storageNode.SetFileName(nrrdName)
            storageNode.WriteData(node)
            print 'Node saved!'
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

'''
class PCampReviewPreprocessorTest(ScriptedLoadableModuleTest):
  """
  This is the test case for your scripted module.
  """

  def setUp(self):
    """ Do whatever is needed to reset the state - typically a scene clear will be enough.
    """
    slicer.mrmlScene.Clear(0)

    self.delayMs = 700

    #TODO: Comment out - sample code for debugging by writing to file
    #logFile = open('d:/pyTestLog.txt', 'a')
    #logFile.write(repr(slicer.modules.batchcontourconversion) + '\n')
    #logFile.close()

  def runTest(self):
    """Run as few or as many tests as needed here.
    """
    self.setUp()

    self.test_PCampReviewPreprocessor_FullTest1()

  def test_PCampReviewPreprocessor_FullTest1(self):
    # Create logic
    self.logic = PCampReviewPreprocessorLogic()

    # Check for modules
    self.assertTrue( slicer.modules.dicomrtimportexport )
    self.assertTrue( slicer.modules.contours )

    self.TestSection_0SetupPathsAndNames()
    self.TestSection_1RetrieveInputData()
    self.TestSection_2OpenDatabase()
    self.TestSection_3ImportStudy()
    self.TestSection_4LoadFirstPatientIntoSlicer()
    self.TestSection_5ConvertContoursToLabelmap()
    self.TestSection_6SaveLabelmaps()
    self.TestSection_0Clear()


  def TestSection_0SetupPathsAndNames(self):
    self.dicomDataDir = self.logic.dataDir + '/TinyRtStudy'
    if not os.access(self.dicomDataDir, os.F_OK):
      os.mkdir(self.dicomDataDir)

    self.dicomZipFilePath = self.logic.dataDir + '/TinyRtStudy.zip'
    self.expectedNumOfFilesInDicomDataDir = 12
    self.outputDir = self.logic.dataDir + '/Output'
    
  def TestSection_1RetrieveInputData(self):
    try:
      import urllib
      downloads = (
          ('http://slicer.kitware.com/midas3/download/folder/2478/TinyRtStudy.zip', self.dicomZipFilePath),
          )

      downloaded = 0
      for url,filePath in downloads:
        if not os.path.exists(filePath) or os.stat(filePath).st_size == 0:
          if downloaded == 0:
            self.delayDisplay('Downloading input data to folder\n' + self.dicomZipFilePath + '.\n\n  It may take a few minutes...',self.delayMs)
          print('Requesting download from %s...' % (url))
          urllib.urlretrieve(url, filePath)
          downloaded += 1
        else:
          self.delayDisplay('Input data has been found in folder ' + self.dicomZipFilePath, self.delayMs)
      if downloaded > 0:
        self.delayDisplay('Downloading input data finished',self.delayMs)

      numOfFilesInDicomDataDir = len([name for name in os.listdir(self.dicomDataDir) if os.path.isfile(self.dicomDataDir + '/' + name)])
      if (numOfFilesInDicomDataDir != self.expectedNumOfFilesInDicomDataDir):
        slicer.app.applicationLogic().Unzip(self.dicomZipFilePath, self.logic.dataDir)
        self.delayDisplay("Unzipping done",self.delayMs)

      numOfFilesInDicomDataDirTest = len([name for name in os.listdir(self.dicomDataDir) if os.path.isfile(self.dicomDataDir + '/' + name)])
      self.assertEqual( numOfFilesInDicomDataDirTest, self.expectedNumOfFilesInDicomDataDir )

    except Exception, e:
      import traceback
      traceback.print_exc()
      self.delayDisplay('Test caused exception!\n' + str(e),self.delayMs*2)

  def TestSection_2OpenDatabase(self):
    self.delayDisplay("Open database",self.delayMs)
    self.logic.OpenDatabase()

    self.assertTrue( slicer.dicomDatabase.isOpen )

  def TestSection_3ImportStudy(self):
    self.delayDisplay("Import study",self.delayMs)
    self.logic.ImportStudy(self.dicomDataDir)

    self.assertTrue( len(slicer.dicomDatabase.patients()) > 0 )
    self.assertTrue( slicer.dicomDatabase.patients()[0] )

  def TestSection_4LoadFirstPatientIntoSlicer(self):
    self.delayDisplay("Load first patient into Slicer",self.delayMs)
    self.logic.LoadFirstPatientIntoSlicer()

  def TestSection_5ConvertContoursToLabelmap(self):
    self.delayDisplay("Convert loaded contours to labelmap",self.delayMs)
    qt.QApplication.setOverrideCursor(qt.QCursor(qt.Qt.BusyCursor))
    try:
      self.labelmapsToSave = self.logic.ConvertContoursToLabelmap()
      self.assertTrue( len(self.labelmapsToSave) > 0 )
    except Exception, e:
      import traceback
      traceback.print_exc()
      self.delayDisplay('Test caused exception!\n' + str(e),self.delayMs*2)
    qt.QApplication.restoreOverrideCursor()

  def TestSection_6SaveLabelmaps(self):
    self.delayDisplay("Save labelmaps to directory\n  %s" % (self.outputDir),self.delayMs)

    self.assertTrue(len(self.labelmapsToSave) > 0)
    qt.QApplication.setOverrideCursor(qt.QCursor(qt.Qt.BusyCursor))

    self.logic.SaveLabelmaps(self.labelmapsToSave,self.outputDir)

    self.delayDisplay('  Labelmaps saved to  %s' % (self.outputDir),self.delayMs)
    qt.QApplication.restoreOverrideCursor()

  def TestSection_0Clear(self):
    self.delayDisplay("Clear database and scene",self.delayMs)

    initialized = slicer.dicomDatabase.initializeDatabase()
    self.assertTrue( initialized )

    slicer.dicomDatabase.closeDatabase()
    self.assertFalse( slicer.dicomDatabase.isOpen )

    #slicer.mrmlScene.Clear(0) #TODO
'''

def main(argv):
  try:
    # Parse command-line arguments
    parser = argparse.ArgumentParser(description="Batch Contour Conversion")
    parser.add_argument("-i", "--input-folder", dest="input_folder", metavar="PATH",
                        default="-", required=True, help="Folder of input DICOM study")
    parser.add_argument("-o", "--output-folder", dest="output_folder", metavar="PATH",
                        default=".", help="Folder for output labelmaps")

    args = parser.parse_args(argv)

    # Check required arguments
    if args.input_folder == "-":
      print('Please specify input DICOM study folder!')
    if args.output_folder == ".":
      print('Current directory is selected as output folder (default). To change it, please specify --output-folder')

    logic = PCampReviewPreprocessorLogic()
    logic.Convert(args.input_folder,args.output_folder)

  except Exception, e:
    print e
  sys.exit()

if __name__ == "__main__":
  main(sys.argv[1:])
