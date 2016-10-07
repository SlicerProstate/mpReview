import argparse, sys, shutil, os
import vtk, qt, ctk, slicer
import DICOMLib
from slicer.ScriptedLoadableModule import *
from SlicerProstateUtils.mixins import ModuleWidgetMixin
#
# mpReviewPreprocessor
#   Prepares the DICOM data to be compatible with mpReview module
#

class mpReviewPreprocessor(ScriptedLoadableModule):
  def __init__(self, parent):
    ScriptedLoadableModule.__init__(self, parent)
    parent.title = "mpReview Preprocessor"
    parent.categories = ["Informatics"]
    parent.dependencies = ["SlicerProstate"]
    parent.contributors = ["Andrey Fedorov (SPL), Robin Weiss (U. of Chicago), Christian Herz (SPL)"]
    parent.helpText = """
    This is a module for conditioning DICOM data for processing using mpReview module
    """
    parent.acknowledgementText = """Development of this module was supported in part by NIH via grants U24CA180918 and U01CA151261."""
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
    return

#
# mpReviewPreprocessorWidget
#

class mpReviewPreprocessorWidget(ScriptedLoadableModuleWidget, ModuleWidgetMixin):

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
    self.progress = self.slicer.util.createProgressDialog()
    self.progress.canceled.connect(lambda : logic.cancelProcess())
    logic.importStudy(self.inputDirButton.directory, progressCallback=self.updateProgressBar)
    logic.convertData(self.outputDirButton.directory, copyDICOM=self.copyDICOMButton.checked,
                      progressCallback=self.updateProgressBar)
    self.progress.canceled.disconnect(lambda : logic.cancelProcess())
    self.progress.close()

  def updateProgressBar(self, **kwargs):
    ModuleWidgetMixin.updateProgressBar(self, progress=self.progress, **kwargs)

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

  def __init__(self):
    ScriptedLoadableModuleLogic.__init__(self)

    self.dataDir = os.path.join(slicer.app.temporaryPath, "mpReviewPreprocessor")
    if os.access(self.dataDir, os.F_OK):
      shutil.rmtree(self.dataDir)

    os.mkdir(self.dataDir)

    self.dicomDatabaseDir = os.path.join(self.dataDir, "CtkDicomDatabase")
    self.indexer = None
    self.patients = []

  def patientFound(self):
    return len(self.patients) > 0

  def updateProgress(self, progress):
    if self.progressCallback:
      self.progressCallback(windowTitle='DICOMIndexer', labelText='Processing files', value=progress)

  def cancelProcess(self):
    self.indexer.cancel()
    self.canceled = True

  def importStudy(self, inputDir, progressCallback=None):
    self.progressCallback = progressCallback
    self.canceled = False
    print('Database location: '+self.dicomDatabaseDir)
    print('FIXME: revert back to the original DB location when done!')
    self.openDatabase()
    print('Input directory: ' + inputDir)
    if not self.indexer:
      self.indexer = ctk.ctkDICOMIndexer()
      self.indexer.connect("progress(int)", self.updateProgress)
    self.indexer.addDirectory(slicer.dicomDatabase, inputDir)
    self.patients = slicer.dicomDatabase.patients()
    print('Import completed, total '+str(len(slicer.dicomDatabase.patients()))+' patients imported')

  def convertData(self, outputDir, copyDICOM, progressCallback=None):
    self.progressCallback = progressCallback
    if self.canceled:
      return
    for patient in self.patients:
      #print patient
      for study in slicer.dicomDatabase.studiesForPatient(patient):
        #print slicer.dicomDatabase.seriesForStudy(study)
        if self.progressCallback:
          self.progressCallback(windowTitle="Processing %s" % study)
        series = slicer.dicomDatabase.seriesForStudy(study)
        for seriesIndex, currentSeries in enumerate(series, start=1):
          if self.canceled:
            return
          # print 'Series:',series
          files = slicer.dicomDatabase.filesForSeries(currentSeries)

          loadable = None
          for pluginName in ['MultiVolumeImporterPlugin','DICOMScalarVolumePlugin']:
            plugin = slicer.modules.dicomPlugins[pluginName]()
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
            seriesDescription = slicer.dicomDatabase.fileValue(dcmFile, '0008,103E')

            if self.progressCallback:
              self.progressCallback(value=seriesIndex, maximum=len(series),
                                    labelText="Processing: {0}".format(seriesDescription))

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

  def openDatabase(self):
    # Open test database and empty it
    if not os.access(self.dicomDatabaseDir, os.F_OK):
      os.mkdir(self.dicomDatabaseDir)

    dicomWidget = slicer.modules.dicom.widgetRepresentation().self()
    dicomWidget.onDatabaseDirectoryChanged(self.dicomDatabaseDir)

    slicer.dicomDatabase.initializeDatabase()

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
    logic.importStudy(args.input_folder)
    logic.convertData(args.output_folder, copyDICOM=args.copyDICOM)

  except Exception, e:
    print e
  sys.exit()

if __name__ == "__main__":
  main(sys.argv[1:])
