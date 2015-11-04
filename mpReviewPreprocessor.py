import os
import DICOMLib
from __main__ import vtk, qt, ctk, slicer
from slicer.ScriptedLoadableModule import *
import argparse
import sys, shutil
from mpReviewPreprocessorSelfTest import mpReviewPreprocessorSelfTestTest as mpReviewPreprocessorTest
#
# mpReviewPreprocessor
#   Prepares the DICOM data to be compatible with mpReview module
#

class mpReviewPreprocessor(ScriptedLoadableModule):
  def __init__(self, parent):
    ScriptedLoadableModule.__init__(self, parent)
    parent.title = "mpReview Preprocessor"
    parent.categories = ["Testing.mpReview Tests"]
    parent.dependencies = []
    parent.contributors = ["Andrey Fedorov (BWH)"]
    parent.helpText = """
    This is a module for conditioning DICOM data for processing using mpReview module
    """
    parent.acknowledgementText = """This module is based on the mpReviewPreprocessor module that was originally developed by Csaba Pinter, PerkLab, Queen's University and was supported through the Applied Cancer Research Unit program of Cancer Care Ontario with funds provided by the Ontario Ministry of Health and Long-Term Care. This module was developed by Andrey Fedorov, BWH, and was supported by NIH via grants U24CA180918 and U01CA151261.""" # replace with organization, grant and thanks.
    self.parent = parent

    # Add this test to the SelfTest module's list for discovery when the module
    # is created.  Since this module may be discovered before SelfTests itself,
    # create the list if it doesn't already exist.
    try:
      slicer.selfTests
    except AttributeError:
      slicer.selfTests = {}
    slicer.selfTests['mpReviewPreprocessor'] = self.runTest

  def runTest(self):
    tester = mpReviewPreprocessorTest()
    tester.runTest()

#
# mpReviewPreprocessorWidget
#

class mpReviewPreprocessorWidget(ScriptedLoadableModuleWidget):
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
    logic = mpReviewPreprocessorLogic()
    logic.Convert(self.inputDirButton.directory, self.outputDirButton.directory,
        copyDICOM=self.copyDICOMButton.checked)

#
# mpReviewPreprocessorLogic
#

class mpReviewPreprocessorLogic(ScriptedLoadableModuleLogic):
  """This class should implement all the actual
  computation done by your module.  The interface
  should be such that other python code can import
  this class and make use of the functionality without
  requiring an instance of the Widget
  """

  @staticmethod
  def makeProgressIndicator(maxVal):
    progressIndicator = qt.QProgressDialog()
    progressIndicator.minimumDuration = 0
    progressIndicator.modal = True
    progressIndicator.setMaximum(maxVal)
    progressIndicator.setValue(0)
    progressIndicator.setWindowTitle("Processing...")
    progressIndicator.show()
    return progressIndicator

  def __init__(self):
    ScriptedLoadableModuleLogic.__init__(self)

    self.dataDir = os.path.join(slicer.app.temporaryPath, "mpReviewPreprocessor")
    if os.access(self.dataDir, os.F_OK):
      shutil.rmtree(self.dataDir)

    os.mkdir(self.dataDir)

    self.dicomDatabaseDir = os.path.join(self.dataDir, "CtkDicomDatabase")

  def Convert(self, inputDir, outputDir, copyDICOM):
    # inputDir = '/Users/fedorov/ImageData/QIICR/QIN PROSTATE/QIN-PROSTATE-01-0001/1.3.6.1.4.1.14519.5.2.1.3671.7001.133687106572018334063091507027'
    print('Database location: '+self.dicomDatabaseDir)
    print('FIXME: revert back to the original DB location when done!')
    self.OpenDatabase()
    print('Input directory: '+inputDir)
    self.ImportStudy(inputDir)

    print('Import completed, total '+str(len(slicer.dicomDatabase.patients()))+' patients imported')

    for patient in slicer.dicomDatabase.patients():
      #print patient
      for study in slicer.dicomDatabase.studiesForPatient(patient):
        #print slicer.dicomDatabase.seriesForStudy(study)
        for series in [l for l in slicer.dicomDatabase.seriesForStudy(study)]:
          #print 'Series:',series
          #print seriesUIDs
          files = slicer.dicomDatabase.filesForSeries(series)

          pluginNames = ['MultiVolumeImporterPlugin','DICOMScalarVolumePlugin']

          loadable = None
          node = None
          dcmFile = None

          for pn in pluginNames:
            plugin = slicer.modules.dicomPlugins[pn]()
            loadables = plugin.examine([files])
            if len(loadables) == 0:
              continue
            if loadables[0].confidence > 0.1:
              loadable = loadables[0]
              break

          if loadable:
            node = plugin.load(loadable)
            dcmFile = loadable.files[0]
            seriesNumber = slicer.dicomDatabase.fileValue(dcmFile, "0020,0011")
            patientID = slicer.dicomDatabase.fileValue(dcmFile, "0010,0020")
            studyDate = slicer.dicomDatabase.fileValue(dcmFile, "0008,0020")
            studyTime = slicer.dicomDatabase.fileValue(dcmFile, "0008,0030")[0:4]

          if node:
            storageNode = node.CreateDefaultStorageNode()
            studyID = patientID+'_'+studyDate+'_'+studyTime
            dirName = os.path.join(outputDir, studyID, "RESOURCES", seriesNumber, "Reconstructions")
            xmlName = os.path.join(dirName, seriesNumber+'.xml')
            try:
              os.makedirs(dirName)
            except:
              pass
            DICOMLib.DICOMCommand("dcm2xml", [dcmFile, xmlName]).start()
            nrrdName = os.path.join(dirName, seriesNumber + ".nrrd")
            #print(nrrdName)
            storageNode.SetFileName(nrrdName)
            storageNode.WriteData(node)

            # copy original DICOMs
            if copyDICOM:
              fileCount = 0
              dirName = os.path.join(outputDir, studyID, "RESOURCES", seriesNumber, "DICOM")
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

def main(argv):
  try:
    # Parse command-line arguments
    parser = argparse.ArgumentParser(description="mpReview preprocessor")
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

    logic = mpReviewPreprocessorLogic()
    logic.Convert(args.input_folder,args.output_folder,copyDICOM=args.copyDICOM)

  except Exception, e:
    print e
  sys.exit()

if __name__ == "__main__":
  main(sys.argv[1:])
