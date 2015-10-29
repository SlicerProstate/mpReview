import os
import vtk, qt, ctk, slicer
from slicer.ScriptedLoadableModule import *
import urllib


class PCampReviewPreprocessorSelfTest(ScriptedLoadableModule):

  def __init__(self, parent):
    ScriptedLoadableModule.__init__(self, parent)
    self.parent.title = "PCampReviewPreprocessorSelfTest"
    self.parent.categories = ["Testing.TestCases"]
    self.parent.dependencies = ["PCampReviewPreprocessor"]
    self.parent.contributors = ["Christian Herz (SPL)"]
    self.parent.helpText = """
    This self test is designed for testing functionality of module PCampReviewPreprocessor.
    """
    self.parent.acknowledgementText = """
    Supported by NIH U01CA151261 (PI Fennessy)
    """


class PCampReviewPreprocessorSelfTestWidget(ScriptedLoadableModuleWidget):

  def setup(self):
    ScriptedLoadableModuleWidget.setup(self)

    parametersCollapsibleButton = ctk.ctkCollapsibleButton()
    parametersCollapsibleButton.text = "Parameters"
    self.layout.addWidget(parametersCollapsibleButton)

    parametersFormLayout = qt.QFormLayout(parametersCollapsibleButton)

    self.runButton = qt.QPushButton("Run")
    self.runButton.toolTip = "Run the algorithm."
    self.runButton.enabled = True
    parametersFormLayout.addRow(self.runButton)

    self.runButton.connect('clicked(bool)', self.onApplyButton)

    self.layout.addStretch(1)

  def cleanup(self):
    pass

  def onApplyButton(self):
    test = PCampReviewPreprocessorSelfTestTest()
    print("Run the test algorithm")
    test.runTest()


class PCampReviewPreprocessorSelfTestLogic(ScriptedLoadableModuleLogic):

  def takeScreenshot(self,name,description,type=-1):
    # show the message even if not taking a screen shot
    slicer.util.delayDisplay('Take screenshot: '+description+'.\nResult is available in the Annotations module.', 3000)

    lm = slicer.app.layoutManager()
    # switch on the type to get the requested window
    widget = 0
    if type == slicer.qMRMLScreenShotDialog.FullLayout:
      # full layout
      widget = lm.viewport()
    elif type == slicer.qMRMLScreenShotDialog.ThreeD:
      # just the 3D window
      widget = lm.threeDWidget(0).threeDView()
    elif type == slicer.qMRMLScreenShotDialog.Red:
      # red slice window
      widget = lm.sliceWidget("Red")
    elif type == slicer.qMRMLScreenShotDialog.Yellow:
      # yellow slice window
      widget = lm.sliceWidget("Yellow")
    elif type == slicer.qMRMLScreenShotDialog.Green:
      # green slice window
      widget = lm.sliceWidget("Green")
    else:
      # default to using the full window
      widget = slicer.util.mainWindow()
      # reset the type so that the node is set correctly
      type = slicer.qMRMLScreenShotDialog.FullLayout

    # grab and convert to vtk image data
    qpixMap = qt.QPixmap().grabWidget(widget)
    qimage = qpixMap.toImage()
    imageData = vtk.vtkImageData()
    slicer.qMRMLUtils().qImageToVtkImageData(qimage,imageData)

    annotationLogic = slicer.modules.annotations.logic()
    annotationLogic.CreateSnapShot(name, description, type, 1, imageData)


class PCampReviewPreprocessorSelfTestTest(ScriptedLoadableModuleTest):

  TEST_DATA_ZIP = 'QIICR-QIN-PROSTATE-001.zip'
  FOLDER_NAME = 'QIN-PROSTATE-001'

  def setUp(self):
    """ Do whatever is needed to reset the state - typically a scene clear will be enough.
    """
    slicer.mrmlScene.Clear(0)
    self.sourceDirectory = None
    self.outputDirectoryPreProcessor = None

  def runTest(self):
    """Run as few or as many tests as needed here.
    """
    self.setUp()

    self.logic = PCampReviewPreprocessorSelfTestLogic()

    self.test_PCampReviewPreProcessor()
    self.delayDisplay('Test passed!')

  def downloadTestData(self):

    baseURL = 'http://slicer.kitware.com/midas3/download?folders=2182'

    self.delayDisplay("Downloading")

    zipFilePath = slicer.app.temporaryPath + '/' + self.TEST_DATA_ZIP
    if not os.path.exists(zipFilePath) or os.stat(zipFilePath).st_size == 0:
      print('Requesting download %s from %s...\n' % (self.TEST_DATA_ZIP, baseURL))
      urllib.urlretrieve(baseURL, zipFilePath)
    self.delayDisplay('Finished with download')

    extractPath = slicer.app.temporaryPath
    extractedPath = os.path.join(extractPath, self.FOLDER_NAME)
    if not os.path.exists(extractedPath):
      applicationLogic = slicer.app.applicationLogic()
      self.delayDisplay("Unzipping to %s" % slicer.app.temporaryPath)
      qt.QDir().mkpath(extractPath)
      self.delayDisplay("Using extract path %s" % extractPath)
      applicationLogic.Unzip(zipFilePath, extractPath)
      print extractedPath
      for file in os.listdir(extractedPath):
        if file.endswith(".zip"):
          applicationLogic.Unzip(os.path.join(extractedPath, file), extractedPath)

    self.sourceDirectory = extractedPath
    self.outputDirectoryPreProcessor = os.path.abspath(self.sourceDirectory)+'_output'

  def test_PCampReviewPreProcessor(self):

    self.delayDisplay("Starting the test")

    if not self.sourceDirectory:
      self.downloadTestData()

    m = slicer.util.mainWindow()
    m.moduleSelector().selectModule('PCampReviewPreprocessor')
    self.delayDisplay('Switched to PCampReviewPreProcessor module')
    self.logic.takeScreenshot('test_PCampReviewPreProcessor-1', 'Startup gui', slicer.qMRMLScreenShotDialog().FullLayout)

    w = slicer.modules.PCampReviewPreprocessorWidget
    w.inputDirButton.directory = self.sourceDirectory
    w.outputDirButton.directory = self.outputDirectoryPreProcessor
    w.copyDICOMButton.checked = True

    w.onRunClicked()