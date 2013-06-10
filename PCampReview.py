import os, dicom
import unittest
from __main__ import vtk, qt, ctk, slicer, string, glob
import CompareVolumes
from Editor import EditorWidget
from EditorLib import EditColor
import Editor
from EditorLib import EditUtil
from EditorLib import EditorLib

from PCampReviewHelper import PCampReviewHelper as PCampReviewHelper

#
# PCampReview
#

class PCampReview:
  def __init__(self, parent):
    parent.title = "PCampReview" # TODO make this more human readable by adding spaces
    parent.categories = ["Radiology"]
    parent.dependencies = []
    parent.contributors = ["PCampReview"] # replace with "Firstname Lastname (Org)"
    parent.helpText = """
    """
    parent.acknowledgementText = """
    Supported by NIH U01CA151261 (PI Fennessy)
""" # replace with organization, grant and thanks.
    self.parent = parent

    # Add this test to the SelfTest module's list for discovery when the module
    # is created.  Since this module may be discovered before SelfTests itself,
    # create the list if it doesn't already exist.
    try:
      slicer.selfTests
    except AttributeError:
      slicer.selfTests = {}
    slicer.selfTests['PCampReview'] = self.runTest

  def runTest(self):
    tester = PCampReviewTest()
    tester.runTest()

#
# qPCampReviewWidget
#

class PCampReviewWidget:
  def __init__(self, parent = None):
    if not parent:
      self.parent = slicer.qMRMLWidget()
      self.parent.setLayout(qt.QVBoxLayout())
      self.parent.setMRMLScene(slicer.mrmlScene)
    else:
      self.parent = parent
    self.layout = self.parent.layout()
    if not parent:
      self.setup()
      self.parent.show()

    # module-specific initialization
    self.inputDataDir = ''

    # TODO: figure out why module/class hierarchy is different
    # between developer builds ans packages
    try:
      # for developer build...
      self.editUtil = EditorLib.EditUtil.EditUtil()
    except AttributeError:
      # for release package...
      self.editUtil = EditorLib.EditUtil()


  def setup(self):
    # Instantiate and connect widgets ...

    #
    # Reload and Test area
    #
    reloadCollapsibleButton = ctk.ctkCollapsibleButton()
    reloadCollapsibleButton.text = "Reload && Test"
    self.layout.addWidget(reloadCollapsibleButton)
    reloadFormLayout = qt.QFormLayout(reloadCollapsibleButton)

    # reload button
    # (use this during development, but remove it when delivering
    #  your module to users)
    self.reloadButton = qt.QPushButton("Reload")
    self.reloadButton.toolTip = "Reload this module."
    self.reloadButton.name = "PCampReview Reload"
    reloadFormLayout.addWidget(self.reloadButton)
    self.reloadButton.connect('clicked()', self.onReload)

    # reload and test button
    # (use this during development, but remove it when delivering
    #  your module to users)
    self.reloadAndTestButton = qt.QPushButton("Reload and Test")
    self.reloadAndTestButton.toolTip = "Reload this module and then run the self tests."
    reloadFormLayout.addWidget(self.reloadAndTestButton)
    self.reloadAndTestButton.connect('clicked()', self.onReloadAndTest)

    # parameters
    self.parameters = {}
    self.settings = qt.QSettings()

    #
    # Step 1: selection of the data directory
    #
    self.step1frame = ctk.ctkCollapsibleButton()
    self.step1frame.text = "Step 1: Data source"
    self.layout.addWidget(self.step1frame)

    # Layout within the dummy collapsible button
    step1Layout = qt.QFormLayout(self.step1frame)

    self.dataDirButton = qt.QPushButton('press to select')
    self.dataDirButton.connect('clicked()', self.onInputDirSelected)
    step1Layout.addRow("Data directory:", self.dataDirButton)
    self.step1frame.collapsed = 0
    self.step1frame.connect('clicked()', self.onStep1Selected)

    # TODO: add here source directory selector

    #
    # Step 2: selection of the study to be analyzed
    #
    self.step2frame = ctk.ctkCollapsibleButton()
    self.step2frame.text = "Step 2: Study selection"
    self.layout.addWidget(self.step2frame)

    # Layout within the dummy collapsible button
    step2Layout = qt.QFormLayout(self.step2frame)
    # TODO: add here source directory selector

    self.studyTable = ItemTable(self.step2frame,headerName='Study Name')
    step2Layout.addWidget(self.studyTable.widget)

    self.step2frame.collapsed = 1
    self.step2frame.connect('clicked()', self.onStep2Selected)

    #
    # Step 3: series selection
    #
    self.step3frame = ctk.ctkCollapsibleButton()
    self.step3frame.text = "Step 3: Series selection"
    self.layout.addWidget(self.step3frame)

    # Layout within the dummy collapsible button
    step3Layout = qt.QFormLayout(self.step3frame)


    self.seriesTable = ItemTable(self.step3frame,headerName='Series Number/Description',multiSelect=True)
    step3Layout.addRow(qt.QLabel('Series to display:'))
    step3Layout.addWidget(self.seriesTable.widget)

    self.step3frame.collapsed = 1
    self.step3frame.connect('clicked()', self.onStep3Selected)

    # get the list of all series for the selected study


    #
    # Step 4: segmentation tools
    #
    self.step4frame = ctk.ctkCollapsibleButton()
    self.step4frame.text = "Step 4: Segmentation"
    self.layout.addWidget(self.step4frame)

    # Layout within the dummy collapsible button
    step4Layout = qt.QFormLayout(self.step4frame)

    # reference node selector
    self.refSelector = qt.QComboBox()
    step4Layout.addRow(qt.QLabel("Reference image: "), self.refSelector)
    self.refSelector.connect('currentIndexChanged(int)', self.onReferenceChanged)

    groupLabel = qt.QLabel('Show series:')
    self.viewGroup = qt.QButtonGroup()
    self.multiView = qt.QRadioButton('All')
    self.singleView = qt.QRadioButton('Reference only')
    self.multiView.setChecked(1)
    self.viewGroup.addButton(self.multiView,1)
    self.viewGroup.addButton(self.singleView,2)
    self.groupWidget = qt.QWidget()
    self.groupLayout = qt.QFormLayout(self.groupWidget)
    self.groupLayout.addRow(self.multiView, self.singleView)
    step4Layout.addRow(groupLabel, self.groupWidget)
    # step4Layout.addRow(groupLabel, self.viewGroup)

    self.viewGroup.connect('buttonClicked(int)', self.onViewUpdateRequested)

    self.step4frame.collapsed = 1
    self.step4frame.connect('clicked()', self.onStep4Selected)

    editorWidgetParent = slicer.qMRMLWidget()
    editorWidgetParent.setLayout(qt.QVBoxLayout())
    editorWidgetParent.setMRMLScene(slicer.mrmlScene)
    self.editorWidget = EditorWidget(parent=editorWidgetParent,showVolumesFrame=False)
    self.editorWidget.setup()
    #self.editorWidget.toolsColor.frame.setVisible(False)

    self.editorParameterNode = self.editUtil.getParameterNode()

    step4Layout.addRow(editorWidgetParent)

    # keep here names of the views created by CompareVolumes logic
    self.viewNames = []

    #
    # Step 5: save results
    #
    #self.step5frame = ctk.ctkCollapsibleButton()
    #self.step5frame.text = "Step 5: Save results"
    #self.layout.addWidget(self.step5frame)

    # Layout within the dummy collapsible button
    #step5Layout = qt.QFormLayout(self.step5frame)
    # TODO: add here source directory selector

    self.saveButton = qt.QPushButton("Save")
    self.layout.addWidget(self.saveButton)
    self.saveButton.connect('clicked()', self.onSaveClicked)

    # Add vertical spacer
    self.layout.addStretch(1)

    self.editorParameterNode = self.editUtil.getParameterNode()

    self.volumesLogic = slicer.modules.volumes.logic()

    # set up temporary directory
    self.tempDir = slicer.app.temporaryPath+'/PCampReview-tmp'
    print('Temporary directory location: '+self.tempDir)
    qt.QDir().mkpath(self.tempDir)

    # these are the PK maps that should be loaded
    self.pkMaps = ['Ktrans','Ve','Auc','TTP','MaxSlope']
    self.helper = PCampReviewHelper()

  def enter(self):
    settings = qt.QSettings()
    userName = settings.value('PCampReview/UserName')
    resultsLocation = settings.value('PCampReview/ResultsLocation')

    if userName == None or userName == '':
      # prompt the user for ID (last name)
      self.namePrompt = qt.QDialog()
      self.namePromptLayout = qt.QVBoxLayout()
      self.namePrompt.setLayout(self.namePromptLayout)
      self.nameLabel = qt.QLabel('Enter your last name:', self.namePrompt)
      import getpass
      self.nameText = qt.QLineEdit(getpass.getuser(), self.namePrompt)
      self.nameButton = qt.QPushButton('OK', self.namePrompt)
      self.nameButton.connect('clicked()', self.onNameEntered)
      self.namePromptLayout.addWidget(self.nameLabel)
      self.namePromptLayout.addWidget(self.nameText)
      self.namePromptLayout.addWidget(self.nameButton)
      self.namePrompt.exec_()

    if resultsLocation == None or resultsLocation == '':
      self.dirPrompt = qt.QDialog()
      self.dirPromptLayout = qt.QVBoxLayout()
      self.dirPrompt.setLayout(self.dirPromptLayout)
      self.dirLabel = qt.QLabel('Choose the directory to store the results:', self.dirPrompt)
      self.dirButton = ctk.ctkDirectoryButton(self.dirPrompt)
      self.dirButtonDone = qt.QPushButton('OK', self.dirPrompt)
      self.dirButtonDone.connect('clicked()', self.onDirEntered)
      self.dirPromptLayout.addWidget(self.dirLabel)
      self.dirPromptLayout.addWidget(self.dirButton)
      self.dirPromptLayout.addWidget(self.dirButtonDone)
      self.dirPrompt.exec_()

    self.parameters['UserName'] = userName
    self.parameters['ResultsLocation'] = resultsLocation

  def onNameEntered(self):
    name = self.nameText.text
    if len(name)>0:
      self.settings.setValue('PCampReview/UserName',name)
      self.namePrompt.close()
      self.parameters['UserName'] = name

  def onDirEntered(self):
    path = self.dirButton.directory
    if len(path)>0:
      self.settings.setValue('PCampReview/ResultsLocation',path)
      self.dirPrompt.close()
      self.parameters['ResultsLocation'] = path

  def onViewUpdateRequested(self, id):
    layoutNode = slicer.util.getNode('*LayoutNode*')
    layoutManager = slicer.app.layoutManager()
    if id == 1:
      # get slice offset from Red slice viewer
      redSliceWidget = layoutManager.sliceWidget('Red')
      redSliceNode = redSliceWidget.mrmlSliceNode()
      redSliceOffset = redSliceNode.GetSliceOffset()
      print('Red slice offset: '+str(redSliceOffset))

      self.helper.setOffsetOnAllSliceWidgets(redSliceOffset)

      # set linking properties on one composite node -- should it apply to
      # all?
      sc = redSliceWidget.mrmlSliceCompositeNode()
      sc.SetLinkedControl(1)
      sc.SetInteractionFlags(4+8+16)

      layoutNode.SetViewArrangement(layoutNode.SlicerLayoutUserView)

    if id == 2:
      layoutNode.SetViewArrangement(layoutNode.SlicerLayoutOneUpRedSliceView)
      if self.refSeriesNumber != '-1':
        ref = self.refSeriesNumber
        redSliceWidget = layoutManager.sliceWidget('Red')
        compositeNode = redSliceWidget.mrmlSliceCompositeNode()
        compositeNode.SetBackgroundVolumeID(self.volumeNodes[ref].GetID())
        compositeNode.SetLabelVolumeID(self.labelNodes[ref].GetID())
        #slicer.app.applicationLogic().PropagateVolumeSelection(0)
        # redSliceWidget.fitSliceToBackground()

  def delayDisplay(self,message,msec=1000):
    """This utility method displays a small dialog and waits.
    This does two things: 1) it lets the event loop catch up
    to the state of the test so that rendering and widget updates
    have all taken place before the test continues and 2) it
    shows the user/developer/tester the state of the test
    so that we'll know when it breaks.
    """
    print(message)
    self.info = qt.QDialog()
    self.infoLayout = qt.QVBoxLayout()
    self.info.setLayout(self.infoLayout)
    self.label = qt.QLabel(message,self.info)
    self.infoLayout.addWidget(self.label)
    qt.QTimer.singleShot(msec, self.info.close)
    self.info.exec_()

  def onSaveClicked(self):
    """ Elements that will be saved:
        * segmentation: label map
        * w/l for each volume
        Convention: create a directory for each type of resource saved,
        then subdirectory for each scan that was analyzed
    """
    segmentationsDir = self.parameters['ResultsLocation']+'/'+self.studyName+'/Segmentations'
    wlSettingsDir = self.parameters['ResultsLocation']+'/'+self.studyName+'/WindowLevelSettings'
    try:
      os.makedirs(segmentationsDir)
      os.makedirs(wlSettingsDir)
    except:
      pass

    # save all label nodes (there should be only one per volume!)
    labelNodes = slicer.util.getNodes('*-label')
    for key in labelNodes.keys():
      sNode = slicer.vtkMRMLVolumeArchetypeStorageNode()
      seriesNumber = string.split(key,":")[0]
      sNode.SetFileName(segmentationsDir+'/'+seriesNumber+'-label.nrrd')
      sNode.SetWriteFileFormat('nrrd')
      sNode.SetURI(None)
      sNode.WriteData(labelNodes[key])
      print(key+' has been saved')

    # save w/l settings for all non-label volume nodes
    volumeNodes = slicer.util.getNodes('vtkMRMLScalarVolumeNode*')
    print('All volume nodes: '+str(volumeNodes))
    for key in volumeNodes.keys():
      vNode = volumeNodes[key]
      if vNode.GetAttribute('LabelMap') == '1':
        continue
      seriesNumber = string.split(key,':')[0]
      print('W/L for series '+seriesNumber+' is '+str(vNode.GetDisplayNode().GetWindow()))
      f = open(wlSettingsDir+'/'+seriesNumber+'-wl.txt','w')
      f.write(str(vNode.GetDisplayNode().GetWindow())+' '+str(vNode.GetDisplayNode().GetLevel()))
      f.close()

    self.helper.infoPopup('Results were saved!')

  def onInputDirSelected(self):
    self.inputDataDir = qt.QFileDialog.getExistingDirectory(self.parent,'Input data directory', '/Users/fedorov/Downloads/TESTSlicer')
    self.dataDirButton.text = self.inputDataDir
    self.parameters['InputDirectory'] = self.inputDataDir
    print(self.inputDataDir)

  '''
  Step 1: Select the directory that has the data
  '''
  def onStep1Selected(self):
    self.step1frame.collapsed = 0
    self.step2frame.collapsed = 1
    self.step3frame.collapsed = 1
    self.step4frame.collapsed = 1

  '''
  Step 2: Select the patient
  '''
  def onStep2Selected(self):
    self.step2frame.collapsed = 0
    self.step1frame.collapsed = 1
    self.step3frame.collapsed = 1
    self.step4frame.collapsed = 1

    studyDirs = []
    # get list of studies
    if not os.path.exists(self.inputDataDir):
      return

    dirs = os.listdir(self.inputDataDir)
    for studyName in dirs:
      if os.path.isdir(self.inputDataDir+'/'+studyName):
        studyDirs.append(studyName)
        print('Adding '+studyName)

    self.studyTable.setContent(studyDirs)

    # TODO: unload all volume nodes that are already loaded

  '''
  Step 3: Select series of interest
  '''
  def onStep3Selected(self):
    print('Entering step 3')

    self.cleanupDir(self.tempDir)

    self.step3frame.collapsed = 0
    self.step2frame.collapsed = 1
    self.step1frame.collapsed = 1
    self.step4frame.collapsed = 1

    selectedItem = self.studyTable.getSelectedItem()
    # check if the study has been selected, otherwise, go back to Step 2
    if selectedItem == None:
      self.onStep2Selected()
      return

    self.parameters['StudyName'] = selectedItem.text()

    print('Selected item text: '+selectedItem.text())
    self.studyName = selectedItem.text()

    # go over all dirs that end in DICOM, get series name
    # Two types of image data that will be displayed:
    #  1) original DICOM data: 'series' maps series number to series
    #  description
    #  2) PK map: 'series' maps PK map code (as defined in self.pkMaps) to the
    #  part of the PK map file name before the .nrrd extension
    self.seriesMap = {}
    tableItems = []
    studyPath = self.inputDataDir+'/'+self.studyName
    for root, subdirs, files in os.walk(self.inputDataDir+'/'+self.studyName):
      if os.path.split(root)[-1] == 'DICOM':
        print('DICOM dir: '+root)
        dcm = dicom.read_file(root+'/'+files[0])
        self.seriesMap[int(dcm.SeriesNumber)] = dcm.SeriesDescription
      # assume that PK maps are in a zip file that is in OncoQuant folder
      if os.path.split(root)[-1] == 'OncoQuant':
        print('Found OncoQuant stuff')
        # copy the right zip file to temp directory
        # hard-coded type of the maps we consider initially
        mapsFileName = 'OncoQuant-TwoParameterModel-ModelAIF.zip'
        import zipfile
        zfile = zipfile.ZipFile(root+'/'+mapsFileName)
        for fname in zfile.namelist():
          for pkname in self.pkMaps:
            if string.find(fname,pkname) > 0:
              print('Found map '+pkname)
              fd = open(self.tempDir+'/'+os.path.split(fname)[-1],'w')
              fd.write(zfile.read(fname))
              fd.close()
              # PK map name is *-<map type>.nrrd
              self.seriesMap[pkname] = string.split(os.path.split(fname)[-1],'.')[0]

    numbers = self.seriesMap.keys()
    numbers.sort()
    for num in numbers:
      tableItems.append(str(num)+': '+self.seriesMap[num])
    self.seriesTable.setContent(tableItems)

    # self.seriesTable.checkAll()
    for row in xrange(self.seriesTable.widget.rowCount):
      item = self.seriesTable.widget.item(row,0)
      if self.helper.isSeriesOfInterest(item.text()):
        item.setCheckState(True)
        print('Checked: '+str(item.checkState()))


  '''
   T2w, sub, ADC, T2map
  '''

  def onStep4Selected(self):
    # set up editor
    self.editorWidget.enter()

    self.step2frame.collapsed = 1
    self.step3frame.collapsed = 1
    self.step1frame.collapsed = 1
    self.step4frame.collapsed = 0

    checkedItems = self.seriesTable.getCheckedItems()

    # if no series selected, go to the previous step
    if len(checkedItems) == 0:
      self.onStep3Selected()
      return

    self.volumeNodes = {}
    self.labelNodes = {}
    self.refSeriesNumber = '-1'

    print('Checked items:')
    ref = None

    self.refSelector.clear()

    # reference selector can have None (initially)
    # user should select reference, which triggers creation of the label and
    # initialization of the editor widget

    # self.refSelector.addItem('None')

    # ignore refSelector events until the selector is populated!
    self.refSelectorIgnoreUpdates = True

    # iterate over all selected items and add them to the reference selector
    for i in checkedItems:
      text = i.text()
      self.refSelector.addItem(text)
      self.delayDisplay('Processing series '+text)
      try:
        guessPkMapName = string.split(text,'-')[-1]
      except:
        guessPkMapName = None
      import string, glob
      if string.find(text, 'DCE')>=0 or string.find(text, 'mapping')>=0:
        dicomPlugin = slicer.modules.dicomPlugins['MultiVolumeImporterPlugin']()
      # get the map type from the string that looks like
      #    Ktrans:PATIENT-Ktrans
      elif guessPkMapName in self.pkMaps:
        # do not use any dicom plugin
        dicomPlugin = None
      else:
        # parse using scalar volume plugin
        dicomPlugin = slicer.modules.dicomPlugins['DICOMScalarVolumePlugin']()

      # text should be formatted as <SeriesNumber : SeriesDescription> !!
      seriesNumber = string.split(text,':')[0]

      if dicomPlugin == None:
        filename = self.tempDir+'/'+string.split(text,':')[-1][1:]+'.nrrd'
        print('Loading volume from '+filename)
        (success,volume) = slicer.util.loadVolume(filename,returnNode=True)
        volume.SetName(guessPkMapName)
        self.volumeNodes[seriesNumber] = volume
        dNode = volume.GetDisplayNode()
        dNode.SetAndObserveColorNodeID('vtkMRMLColorTableNodeFileHotToColdRainbow.txt')
        if guessPkMapName == 'Ktrans' or guessPkMapName == 'Ve':
          dNode.SetWindowLevel(5.0,2.5)
        continue

      seriesDir = self.inputDataDir+'/'+self.studyName+'/SCANS/'+seriesNumber+'/DICOM'
      files = glob.glob(seriesDir+'/*.dcm')
      allLoadables = dicomPlugin.examine([files])
      selectedLoadables = []

      for sv in allLoadables:
        if sv.selected:
          selectedLoadables.append(sv)
          volume = dicomPlugin.load(sv)
          volume.SetName(text)
          self.volumeNodes[seriesNumber] = volume
          if string.find(text, 'T2')>0 and string.find(text, 'AX')>0:
            print('Setting reference to '+text)
            ref = seriesNumber
      print('Have this many loadables for series '+str(seriesNumber)+' : '+str(len(selectedLoadables)))

    print('Will now set up compares')
    self.cvLogic = CompareVolumes.CompareVolumesLogic()
    self.viewNames = [self.volumeNodes[ref].GetName()]
    for vNode in self.volumeNodes.values():
      if vNode != self.volumeNodes[ref]:
        self.viewNames.append(vNode.GetName())
    # this helper function implements fuzzy logic to figure out the matching to
    # a specific series of interest for this project
    # pkMaps
    self.viewNames = self.helper.abbreviateNames(self.viewNames,self.pkMaps)
    print('Abbreviated names:'+str(self.viewNames))
    self.cvLogic.viewerPerVolume(self.volumeNodes.values(), self.volumeNodes[ref],viewNames=self.viewNames)
    print('Compares set up')
    if ref:
      self.cvLogic.rotateToVolumePlanes(self.volumeNodes[ref])

    self.refSelectorIgnoreUpdates = False

    self.onReferenceChanged(0)
    self.onViewUpdateRequested(2)
    self.onViewUpdateRequested(1)
    self.helper.setOpacityOnAllSliceWidgets(1.0)

  def onReferenceChanged(self, id):
    if self.refSelectorIgnoreUpdates:
      return
    text = self.refSelector.currentText
    print('Current reference node: '+text)
    if text != 'None':
      self.refSeriesNumber = string.split(text,':')[0]
      ref = self.refSeriesNumber
    else:
      return

    try:
      # check if already have a label for this node
      refLabel = self.labelNodes[ref]
    except KeyError:
      # create a new label
      labelName = self.volumeNodes[ref].GetName()+'-label'
      refLabel = self.volumesLogic.CreateAndAddLabelVolume(slicer.mrmlScene,self.volumeNodes[ref],labelName)
      self.labelNodes[ref] = refLabel

    self.cvLogic = CompareVolumes.CompareVolumesLogic()
    self.cvLogic.viewerPerVolume(self.volumeNodes.values(),background=self.volumeNodes[ref],label=refLabel,viewNames=self.viewNames)
    if ref:
      print('Rotate to reference '+self.volumeNodes[ref].GetName())
      self.cvLogic.rotateToVolumePlanes(self.volumeNodes[ref])

    print('Setting master node for the Editor to '+self.volumeNodes[ref].GetID())
    self.editorWidget.setMasterNode(self.volumeNodes[ref])
    self.editorWidget.setMergeNode(self.labelNodes[ref])

    self.editorParameterNode.Modified()

  def cleanupDir(self, d):
    if not os.path.exists(d):
      return
    oldFiles = os.listdir(d)
    for f in oldFiles:
      path = d+'/'+f
      if not os.path.isdir(path):
        os.unlink(d+'/'+f)

  def onSelect(self):
    self.applyButton.enabled = self.inputSelector.currentNode() and self.outputSelector.currentNode()

  def onApplyButton(self):
    logic = PCampReviewLogic()
    print("Run the algorithm")
    logic.run(self.inputSelector.currentNode(), self.outputSelector.currentNode())

  def onReload(self,moduleName="PCampReview"):
    """Generic reload method for any scripted module.
    ModuleWizard will subsitute correct default moduleName.
    """
    import imp, sys, os, slicer, CompareVolumes, dicom, string

    widgetName = moduleName + "Widget"

    # reload the source code
    # - set source file path
    # - load the module to the global space
    filePath = eval('slicer.modules.%s.path' % moduleName.lower())
    p = os.path.dirname(filePath)
    if not sys.path.__contains__(p):
      sys.path.insert(0,p)
    fp = open(filePath, "r")
    globals()[moduleName] = imp.load_module(
        moduleName, fp, filePath, ('.py', 'r', imp.PY_SOURCE))
    fp.close()

    # rebuild the widget
    # - find and hide the existing widget
    # - create a new widget in the existing parent
    parent = slicer.util.findChildren(name='%s Reload' % moduleName)[0].parent().parent()
    for child in parent.children():
      try:
        child.hide()
      except AttributeError:
        pass
    # Remove spacer items
    item = parent.layout().itemAt(0)
    while item:
      parent.layout().removeItem(item)
      item = parent.layout().itemAt(0)
    # create new widget inside existing parent
    globals()[widgetName.lower()] = eval(
        'globals()["%s"].%s(parent)' % (moduleName, widgetName))
    globals()[widgetName.lower()].setup()

  def onReloadAndTest(self,moduleName="PCampReview"):
    try:
      self.onReload()
      evalString = 'globals()["%s"].%sTest()' % (moduleName, moduleName)
      tester = eval(evalString)
      tester.runTest()
    except Exception, e:
      import traceback
      traceback.print_exc()
      qt.QMessageBox.warning(slicer.util.mainWindow(),
          "Reload and Test", 'Exception!\n\n' + str(e) + "\n\nSee Python Console for Stack Trace")


#
# PCampReviewLogic
#

class PCampReviewLogic:
  """This class should implement all the actual
  computation done by your module.  The interface
  should be such that other python code can import
  this class and make use of the functionality without
  requiring an instance of the Widget
  """
  def __init__(self):
    pass

  def hasImageData(self,volumeNode):
    """This is a dummy logic method that
    returns true if the passed in volume
    node has valid image data
    """
    if not volumeNode:
      print('no volume node')
      return False
    if volumeNode.GetImageData() == None:
      print('no image data')
      return False
    return True

  def run(self,inputVolume,outputVolume):
    """
    Run the actual algorithm
    """
    return True


class PCampReviewTest(unittest.TestCase):
  """
  This is the test case for your scripted module.
  """

  def delayDisplay(self,message,msec=1000):
    """This utility method displays a small dialog and waits.
    This does two things: 1) it lets the event loop catch up
    to the state of the test so that rendering and widget updates
    have all taken place before the test continues and 2) it
    shows the user/developer/tester the state of the test
    so that we'll know when it breaks.
    """
    print(message)
    self.info = qt.QDialog()
    self.infoLayout = qt.QVBoxLayout()
    self.info.setLayout(self.infoLayout)
    self.label = qt.QLabel(message,self.info)
    self.infoLayout.addWidget(self.label)
    qt.QTimer.singleShot(msec, self.info.close)
    self.info.exec_()

  def setUp(self):
    """ Do whatever is needed to reset the state - typically a scene clear will be enough.
    """
    slicer.mrmlScene.Clear(0)

  def runTest(self):
    """Run as few or as many tests as needed here.
    """
    self.setUp()
    self.test_PCampReview1()

  def test_PCampReview1(self):
    """ Ideally you should have several levels of tests.  At the lowest level
    tests sould exercise the functionality of the logic with different inputs
    (both valid and invalid).  At higher levels your tests should emulate the
    way the user would interact with your code and confirm that it still works
    the way you intended.
    One of the most important features of the tests is that it should alert other
    developers when their changes will have an impact on the behavior of your
    module.  For example, if a developer removes a feature that you depend on,
    your test should break so they know that the feature is needed.
    """

    mainWidget = slicer.modules.pcampreview.widgetRepresentation().self()

    self.delayDisplay("Starting the test here!")
    #
    # first, get some data
    #
    mainWidget.onStep1Selected()
    self.delayDisplay('1')

    mainWidget.onStep2Selected()
    self.delayDisplay('2')

    studyItem = mainWidget.studyTable.widget.item(0,0)
    studyItem.setSelected(1)

    mainWidget.onStep3Selected()
    self.delayDisplay('3')
    seriesItem = mainWidget.seriesTable.widget.item(0,0)
    seriesItem.setCheckState(1)

    mainWidget.onStep4Selected()
    self.delayDisplay('4')


    self.delayDisplay('Test passed!')


class ItemTable(object):

  def __init__(self,parent, headerName, multiSelect=False, width=100):
    self.widget = qt.QTableWidget(parent)
    # self.widget.setMinimumWidth(width)
    self.widget.setColumnCount(1)
    self.widget.setHorizontalHeaderLabels([headerName])
    self.widget.horizontalHeader().setResizeMode(0, qt.QHeaderView.Stretch)
    self.widget.horizontalHeader().stretchLastSection = 1
    self.widget.setEditTriggers(qt.QAbstractItemView.NoEditTriggers)
    self.multiSelect = multiSelect
    if self.multiSelect == False:
      self.widget.setSelectionMode(qt.QAbstractItemView.SingleSelection)
    self.width = width
    self.items = []
    self.strings = []
    #self.loadables = {}
    #self.setLoadables([])

  def addContentItemRow(self,string,row):
    """Add a row to the loadable table
    """
    # name and check state
    print('Appending '+string)
    self.strings.append(string)
    item = qt.QTableWidgetItem(string)
    item.setCheckState(0)
    if not self.multiSelect:
      item.setFlags(33)
    else:
      # allow checkboxes interaction
      item.setFlags(49)
    self.items.append(item)
    self.widget.setItem(row,0,item)
    item.setToolTip('')
    # reader

  def setContent(self,strings):
    """Load the table widget with a list
    of volume options (of class DICOMVolume)
    """
    self.widget.clearContents()
    self.widget.setColumnWidth(0,int(self.width))
    self.widget.setRowCount(len(strings))
    # self.items = []
    row = 0

    for s in strings:
      self.addContentItemRow(s,row)
      row += 1

    self.widget.setVerticalHeaderLabels(row * [""])

  def uncheckAll(self):
    for row in xrange(self.widget.rowCount):
      item = self.widget.item(row,0)
      item.setCheckState(False)

  def checkAll(self):
    for row in xrange(self.widget.rowCount):
      item = self.widget.item(row,0)
      item.setCheckState(True)
      print('Checked: '+str(item.checkState()))

  def getSelectedItem(self):
    for row in xrange(self.widget.rowCount):
      item = self.widget.item(row,0)
      if item.isSelected():
        return item

  def getCheckedItems(self):
    checkedItems = []
    for row in xrange(self.widget.rowCount):
      item = self.widget.item(row,0)
      if item.checkState():
        checkedItems.append(item)
    return checkedItems


  '''
  def updateCheckstate(self):
    for row in xrange(self.widget.rowCount):
      item = self.widget.item(row,0)
      self.loadables[row].selected = (item.checkState() != 0)
  '''

