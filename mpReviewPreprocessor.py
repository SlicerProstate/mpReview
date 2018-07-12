import argparse, sys, shutil, os, logging
import qt, ctk, slicer
import DICOMLib
from DICOMLib.DICOMUtils import TemporaryDICOMDatabase
from slicer.ScriptedLoadableModule import *
from SlicerDevelopmentToolboxUtils.mixins import ModuleWidgetMixin, ModuleLogicMixin

#
# mpReviewPreprocessor
#   Prepares the DICOM data to be compatible with mpReview module
#

class mpReviewPreprocessor(ScriptedLoadableModule):
  def __init__(self, parent):
    ScriptedLoadableModule.__init__(self, parent)
    parent.title = "mpReview Preprocessor"
    parent.categories = ["Informatics"]
    parent.dependencies = ["SlicerDevelopmentToolbox"]
    parent.contributors = ["Andrey Fedorov (SPL)", "Robin Weiss (U. of Chicago)", "Christian Herz (SPL)"]
    parent.helpText = """
    This is a module for conditioning DICOM data for processing using mpReview module
    """
    parent.acknowledgementText = """
    Development of this module was supported in part by NIH via grants U24CA180918 and U01CA151261.
    """
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
    ScriptedLoadableModuleWidget.setup(self)

    parametersCollapsibleButton = ctk.ctkCollapsibleButton()
    parametersCollapsibleButton.text = "Parameters"
    self.layout.addWidget(parametersCollapsibleButton)

    parametersFormLayout = qt.QFormLayout(parametersCollapsibleButton)

    self.inputDirButton = ctk.ctkDirectoryButton()
    parametersFormLayout.addRow("Input directory:", self.inputDirButton)

    self.outputDirButton = ctk.ctkDirectoryButton()
    parametersFormLayout.addRow("Output directory:", self.outputDirButton)

    self.copyDICOMButton = qt.QCheckBox()
    self.copyDICOMButton.setChecked(0)
    parametersFormLayout.addRow("Organize DICOMs:", self.copyDICOMButton)

    applyButton = qt.QPushButton('Run')
    parametersFormLayout.addRow(applyButton)

    applyButton.connect('clicked()', self.onRunClicked)

  def onRunClicked(self):
    logic = mpReviewPreprocessorLogic()
    self.progress = self.createProgressDialog()
    self.progress.canceled.connect(lambda: logic.cancelProcess())
    logic.importAndProcessData(self.inputDirButton.directory, self.outputDirButton.directory,
                               copyDICOM=self.copyDICOMButton.checked,
                               progressCallback=self.updateProgressBar)
    self.progress.canceled.disconnect(lambda : logic.cancelProcess())
    self.progress.close()

  def updateProgressBar(self, **kwargs):
    ModuleWidgetMixin.updateProgressBar(self, progress=self.progress, **kwargs)

#
# mpReviewPreprocessorLogic
#

class mpReviewPreprocessorLogic(ScriptedLoadableModuleLogic, ModuleLogicMixin):
  """This class should implement all the actual
  computation done by your module.  The interface
  should be such that other python code can import
  this class and make use of the functionality without
  requiring an instance of the Widget
  """

  @property
  def dicomDatabase(self):
    return slicer.dicomDatabase

  @property
  def patients(self):
    return self.dicomDatabase.patients()

  def __init__(self):
    ScriptedLoadableModuleLogic.__init__(self)

    self.dataDir = os.path.join(slicer.app.temporaryPath, "mpReviewPreprocessor")
    if os.access(self.dataDir, os.F_OK):
      shutil.rmtree(self.dataDir)

    self.createDirectory(self.dataDir)

  def patientFound(self):
    return len(self.patients) > 0

  def updateProgressBar(self, **kwargs):
    if self.progressCallback:
      self.progressCallback(**kwargs)

  def cancelProcess(self):
    self.indexer.cancel()
    self.canceled = True

  def importAndProcessData(self, inputDir, outputDir, copyDICOM, progressCallback=None):
    self.canceled = False
    with TemporaryDICOMDatabase(os.path.join(self.dataDir, "CtkDICOMDatabase")) as db:
      self._importStudy(inputDir, progressCallback)
      success = self._processData(outputDir, copyDICOM, progressCallback)
    return success

  def _importStudy(self, inputDir, progressCallback=None):
    self.progressCallback = progressCallback
    logging.debug('Input directory: %s' % inputDir)
    self.indexer = getattr(self, "indexer", None)
    if not self.indexer:
      self.indexer = ctk.ctkDICOMIndexer()

      def updateProgress(progress):
        if self.progressCallback:
          self.progressCallback(windowTitle='DICOMIndexer', labelText='Processing files', value=progress)
      self.indexer.connect("progress(int)", updateProgress)
    self.indexer.addDirectory(self.dicomDatabase, inputDir)
    logging.debug('Import completed, total %s patients imported' % len(self.patients))

  def _processData(self, outputDir, copyDICOM, progressCallback=None):
    self.progressCallback = progressCallback

    for patient in self.patients:
      self.updateProgressBar(windowTitle="Processing patient %s" % patient)
      for study in self.dicomDatabase.studiesForPatient(patient):
        #print self.dicomDatabase.seriesForStudy(study)
        self.updateProgressBar(windowTitle="Processing %s" % study)
        series = self.dicomDatabase.seriesForStudy(study)
        for seriesIndex, currentSeries in enumerate(series, start=1):
          if self.canceled:
            return False
          files = self.dicomDatabase.filesForSeries(currentSeries)

          if len(files):
            seriesDescription = self.dicomDatabase.fileValue(files[0], '0008,103E')

            self.updateProgressBar(value=seriesIndex, maximum=len(series),
                                  labelText="Processing: %s" % seriesDescription)
          
            plugin, loadable = self._getPluginAndLoadableForFiles(seriesDescription, files)

            if loadable and plugin:
              self.updateProgressBar(labelText="Starting conversion process: %s" % seriesDescription)
              converter = Converter(outputDir, copyDICOM)
              converter.convertData(plugin, loadable)

    return True

  def _getPluginAndLoadableForFiles(self, seriesDescription, files):
    if self.progressCallback:
      self.progressCallback(labelText="Examining loadables: %s" % seriesDescription)
    for pluginName in ['MultiVolumeImporterPlugin', 'DICOMScalarVolumePlugin']:
      plugin = slicer.modules.dicomPlugins[pluginName]()
      loadables = plugin.examine([files])
      if len(loadables) == 0:
        continue
      loadables.sort(key=lambda x: x.confidence, reverse=True)
      if loadables[0].confidence > 0.1:
        return plugin, loadables[0]
    return None, None


class Converter(object):

  @property
  def dicomDatabase(self):
    return slicer.dicomDatabase

  def __init__(self, outputDir, copyDICOM=False):
    self.outputDir = outputDir
    self.copyDICOM = copyDICOM

  def convertData(self, plugin, loadable):
    node = plugin.load(loadable)
    dcmFile = loadable.files[0]
    seriesNumber = self.dicomDatabase.fileValue(dcmFile, "0020,0011")
    patientID = self.dicomDatabase.fileValue(dcmFile, "0010,0020")
    studyDate = self.dicomDatabase.fileValue(dcmFile, "0008,0020")
    studyTime = self.dicomDatabase.fileValue(dcmFile, "0008,0030")[0:4]

    if node:
      storageNode = node.CreateDefaultStorageNode()
      studyID = '{}_{}_{}'.format(patientID, studyDate, studyTime)
      dirName = os.path.join(self.outputDir, studyID, "RESOURCES", seriesNumber, "Reconstructions")
      xmlName = os.path.join(dirName, seriesNumber + '.xml')
      try:
        os.makedirs(dirName)
      except:
        pass
      DICOMLib.DICOMCommand("dcm2xml", [dcmFile, xmlName]).start()
      nrrdName = os.path.join(dirName, seriesNumber + ".nrrd")
      # print(nrrdName)
      storageNode.SetFileName(nrrdName)
      storageNode.WriteData(node)

      if self.copyDICOM:
        fileCount = 0
        dirName = os.path.join(self.outputDir, studyID, "RESOURCES", seriesNumber, "DICOM")
        try:
          os.makedirs(dirName)
        except:
          pass
        for dcm in loadable.files:
          shutil.copy(dcm, os.path.join(dirName, "%06d.dcm" % fileCount))
          fileCount = fileCount + 1
    else:
      print 'No node!'


def main(argv):
  try:
    parser = argparse.ArgumentParser(description="mpReview preprocessor")
    parser.add_argument("-i", "--input-folder", dest="input_folder", metavar="PATH",
                        default="-", required=True, help="Folder of input DICOM files (can contain sub-folders)")
    parser.add_argument("-o", "--output-folder", dest="output_folder", metavar="PATH",
                        default=".", help="Folder to save converted datasets")
    parser.add_argument("-d","--copyDICOM",dest="copyDICOM",type=bool,default=False,
                        help="Organize DICOM files in the output directory")
    args = parser.parse_args(argv)

    if args.input_folder == "-":
      print('Please specify input DICOM study folder!')
    if args.output_folder == ".":
      print('Current directory is selected as output folder (default). To change it, please specify --output-folder')

    logic = mpReviewPreprocessorLogic()
    logic.importAndProcessData(args.input_folder, args.output_folder, copyDICOM=args.copyDICOM)
  except Exception, e:
    print e
  sys.exit()

if __name__ == "__main__":
  main(sys.argv[1:])
