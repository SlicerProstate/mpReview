from __future__ import division
import os, json, xml.dom.minidom, string, glob, re, math
import unittest
from __main__ import vtk, qt, ctk, slicer
import CompareVolumes
from Editor import EditorWidget
from EditorLib import EditColor
import Editor
from EditorLib import EditUtil
from EditorLib import EditorLib

import PCampReviewLib

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
    self.webFormURL = ''

    self.PCampReviewColorNode = slicer.vtkMRMLColorTableNode()
    colorNode = self.PCampReviewColorNode
    colorNode.SetName('PCampReview')
    slicer.mrmlScene.AddNode(colorNode)
    colorNode.SetTypeToUser()
    moduleName="PCampReview"
    modulePath = eval('slicer.modules.%s.path' % moduleName.lower()).replace(moduleName+".py","")
    colorFile = modulePath + "Resources/Colors/PCampReviewColors.csv"
    with open(colorFile) as f:
      n = sum(1 for line in f)
    colorNode.SetNumberOfColors(n-1)
    import csv
    self.structureNames = []
    with open(colorFile, 'rb') as csvfile:
      reader = csv.DictReader(csvfile, delimiter=',')
      for index,row in enumerate(reader):
        colorNode.SetColor(index,row['Label'],float(row['R'])/255,
                float(row['G'])/255,float(row['B'])/255,float(row['A']))
        self.structureNames.append(row['Label'])

    # TODO: figure out why module/class hierarchy is different
    # between developer builds ans packages
    try:
      # for developer build...
      self.editUtil = EditorLib.EditUtil.EditUtil()
    except AttributeError:
      # for release package...
      self.editUtil = EditorLib.EditUtil()
    # mrml node for invoking command line modules
    self.CLINode = None

  def isSeriesOfInterest(self,desc):
    discardThose = ['SAG','COR','PURE','mapping','DWI','breath','3D DCE','loc','Expo','Map','MAP','POST','ThreeParameter','AutoAIF','BAT','-Slope','PkRsqr']
    for d in discardThose:
      if string.find(desc,d)>=0:
        return False
    return True

  def abbreviateNames(self, longNames, fullMatch):
    shortNames = []
    firstADC = True
    for name in longNames:
      print(str(shortNames))
      if name in fullMatch:
        shortNames.append(name)
      elif string.find(name,'T2')>0:
        shortNames.append('T2')
      elif string.find(name,'T1')>0:
        shortNames.append('T1')
      elif string.find(name,'Apparent Diffusion Coefficient')>0:
        if firstADC:
          shortNames.append('ADCb500')
          firstADC = False
        else:
          shortNames.append('ADCb1400')
      else:
        shortNames.append('Subtract')
    return shortNames

  def abbreviateName(self, meta):
    try:
      descr = meta['SeriesDescription']
      seriesNumber = meta['SeriesNumber']
    except:
      descr = meta['DerivedSeriesDescription']
      seriesNumber = meta['DerivedSeriesNumber']
    abbr = 'Unknown'
    if descr.find('Apparent Diffusion Coeff')>=0:
      abbr = 'ADC'
    if descr.find('T2')>=0:
      abbr = 'T2'
    if descr.find('T1')>=0:
      abbr = 'T1'
    if descr.find('Ktrans')>=0:
      abbr = 'Ktrans'
    if descr.find('Ve')>=0:
      abbr = 've'
    if descr.find('MaxSlope')>=0:
      abbr = 'MaxSlope'
    if descr.find('TTP')>=0:
      abbr = 'TTP'
    if descr.find('Auc')>=0:
      abbr = 'AUC'
    if re.search('[a-zA-Z]',descr) == None:
      abbr = 'Subtract'
    return seriesNumber+'-'+abbr

  def setOffsetOnAllSliceWidgets(self,offset):
    layoutManager = slicer.app.layoutManager()
    widgetNames = layoutManager.sliceViewNames()
    for wn in widgetNames:
      widget = layoutManager.sliceWidget(wn)
      node = widget.mrmlSliceNode()
      node.SetSliceOffset(offset)

      sc = widget.mrmlSliceCompositeNode()
      sc.SetLinkedControl(1)
      sc.SetInteractionFlagsModifier(4+8+16)

  def setOpacityOnAllSliceWidgets(self,opacity):
    layoutManager = slicer.app.layoutManager()
    widgetNames = layoutManager.sliceViewNames()
    for wn in widgetNames:
      widget = layoutManager.sliceWidget(wn)
      sc = widget.mrmlSliceCompositeNode()
      sc.SetForegroundOpacity(opacity)

  def infoPopup(self,message):
    messageBox = qt.QMessageBox()
    messageBox.information(None, 'Slicer mpMRI review', message)

  def setup(self):
    # Instantiate and connect widgets ...

    #
    # Reload and Test area
    #
    reloadCollapsibleButton = ctk.ctkCollapsibleButton()
    reloadCollapsibleButton.text = "Reload && Test"
    #self.layout.addWidget(reloadCollapsibleButton)
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
    self.step1frame = ctk.ctkCollapsibleGroupBox()
    self.step1frame.setTitle("Step 1: Data source")
    self.layout.addWidget(self.step1frame)

    # Layout within the dummy collapsible button
    step1Layout = qt.QFormLayout(self.step1frame)

    self.dataDirButton = qt.QPushButton(str(self.settings.value('PCampReview/InputLocation')))
    self.dataDirButton.connect('clicked()', self.onInputDirSelected)
    step1Layout.addRow("Select data directory:", self.dataDirButton)
    self.inputDirLabel = qt.QLabel()
    step1Layout.addRow(self.inputDirLabel)
    self.resultsDirLabel = qt.QLabel()
    step1Layout.addRow(self.resultsDirLabel)
    self.step1frame.collapsed = 0
    self.step1frame.connect('clicked()', self.onStep1Selected)

    # TODO: add here source directory selector

    #
    # Step 2: selection of the study to be analyzed
    #
    self.step2frame = ctk.ctkCollapsibleGroupBox()
    self.step2frame.setTitle("Step 2: Study selection")
    self.layout.addWidget(self.step2frame)

    # Layout within the dummy collapsible button
    step2Layout = qt.QFormLayout(self.step2frame)
    # TODO: add here source directory selector

    self.step2frame.collapsed = 1
    self.step2frame.connect('clicked()', self.onStep2Selected)

    self.studiesView = qt.QListView()
    self.studiesView.setObjectName('StudiesTable')
    self.studiesView.setSpacing(3)
    self.studiesModel = qt.QStandardItemModel()
    self.studiesModel.setHorizontalHeaderLabels(['Study ID'])
    self.studiesView.setModel(self.studiesModel)
    self.studiesView.setEditTriggers(qt.QAbstractItemView.NoEditTriggers)
    self.studiesView.connect('clicked(QModelIndex)', self.studySelected)
    step2Layout.addWidget(self.studiesView)

    #
    # Step 3: series selection
    #
    self.step3frame = ctk.ctkCollapsibleGroupBox()
    self.step3frame.setTitle("Step 3: Series selection")
    self.layout.addWidget(self.step3frame)

    # Layout within the dummy collapsible button
    step3Layout = qt.QFormLayout(self.step3frame)

    self.seriesView = qt.QListView()
    self.seriesView.setObjectName('SeriesTable')
    self.seriesView.setSpacing(3)
    self.seriesModel = qt.QStandardItemModel()
    self.seriesModel.setHorizontalHeaderLabels(['Series ID'])
    self.seriesView.setModel(self.seriesModel)
    self.seriesView.setSelectionMode(qt.QAbstractItemView.ExtendedSelection)
    self.seriesView.connect('clicked(QModelIndex)', self.seriesSelected)
    self.seriesView.setEditTriggers(qt.QAbstractItemView.NoEditTriggers)
    step3Layout.addWidget(self.seriesView)

    self.step3frame.collapsed = 1
    self.step3frame.connect('clicked()', self.onStep3Selected)

    # get the list of all series for the selected study


    #
    # Step 4: segmentation tools
    #
    self.step4frame = ctk.ctkCollapsibleGroupBox()
    self.step4frame.setTitle("Step 4: Segmentation")
    self.layout.addWidget(self.step4frame)

    # Layout within the dummy collapsible button
    step4Layout = qt.QFormLayout(self.step4frame)

    # reference node selector
    # TODO: use MRML selector here ?
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
    self.editorWidget = EditorWidget(parent=editorWidgetParent)
    self.editorWidget.setup()

    volumesFrame = self.editorWidget.volumes
    # hide unwanted widgets
    for widgetName in ['AllButtonsFrameButton','ReplaceModelsCheckBox',
      'MasterVolumeFrame','MergeVolumeFrame','SplitStructureButton']:
      widget = slicer.util.findChildren(volumesFrame,widgetName)[0]
      widget.hide()

    perStructureFrame = slicer.util.findChildren(volumesFrame,
                        'PerStructureVolumesFrame')[0]
    perStructureFrame.collapsed = False

    buttonsFrame = slicer.util.findChildren(volumesFrame,'ButtonsFrame')[0]
    '''
    updateViewsButton = qt.QPushButton('Update Views')
    buttonsFrame.layout().addWidget(updateViewsButton)
    updateViewsButton.connect("clicked()", self.updateViews)
    '''

    lm = slicer.app.layoutManager()
    redWidget = lm.sliceWidget('Red')
    controller = redWidget.sliceController()
    moreButton = slicer.util.findChildren(controller,'MoreButton')[0]
    moreButton.toggle()
    # labelMapOutlineButton = slicer.util.findChildren(
    #                         controller,'LabelMapOutlineButton')[0]
    # buttonsFrame.layout().addWidget(labelMapOutlineButton)

    #self.editorWidget.toolsColor.frame.setVisible(False)

    self.editorParameterNode = self.editUtil.getParameterNode()
    self.editorParameterNode.SetParameter('propagationMode',
                             str(slicer.vtkMRMLApplicationLogic.LabelLayer))

    step4Layout.addRow(editorWidgetParent)

    self.modelsVisibility = True
    modelsFrame = qt.QFrame()
    modelsHLayout = qt.QHBoxLayout(modelsFrame)
    perStructureFrame.layout().addWidget(modelsFrame)

    modelsLabel = qt.QLabel('Structure Models: ')
    modelsHLayout.addWidget(modelsLabel)

    buildModelsButton = qt.QPushButton('Make')
    modelsHLayout.addWidget(buildModelsButton)
    buildModelsButton.connect("clicked()", self.onBuildModels)

    self.modelsVisibilityButton = qt.QPushButton('Hide')
    self.modelsVisibilityButton.checkable = True
    modelsHLayout.addWidget(self.modelsVisibilityButton)
    self.modelsVisibilityButton.connect("toggled(bool)", self.onModelsVisibilityButton)
    
    self.labelMapOutlineButton = qt.QPushButton('Outline')
    self.labelMapOutlineButton.checkable = True
    modelsHLayout.layout().addWidget(self.labelMapOutlineButton)
    self.labelMapOutlineButton.connect('toggled(bool)', self.setLabelOutline)
    
    modelsHLayout.addStretch(1)

    # keep here names of the views created by CompareVolumes logic
    self.viewNames = []

    #
    # Step 6: save results
    #
    #self.step5frame = ctk.ctkCollapsibleButton()
    #self.step5frame.text = "Step 5: Save results"
    #self.layout.addWidget(self.step5frame)

    # Layout within the dummy collapsible button
    #step5Layout = qt.QFormLayout(self.step5frame)
    # TODO: add here source directory selector

    self.qaButton = qt.QPushButton("PI-RADS v2 review form")
    self.layout.addWidget(self.qaButton)
    self.qaButton.connect('clicked()',self.onQAFormClicked)

    self.saveButton = qt.QPushButton("Save")
    self.layout.addWidget(self.saveButton)
    self.saveButton.connect('clicked()', self.onSaveClicked)

    '''
    self.piradsButton = qt.QPushButton("PI-RADS review")
    self.layout.addWidget(self.piradsButton)
    # self.piradsButton.connect('clicked()',self.onPiradsClicked)
    '''

    # Add vertical spacer
    self.layout.addStretch(1)

    self.volumesLogic = slicer.modules.volumes.logic()

    # set up temporary directory
    self.tempDir = slicer.app.temporaryPath+'/PCampReview-tmp'
    print('Temporary directory location: '+self.tempDir)
    qt.QDir().mkpath(self.tempDir)

    # these are the PK maps that should be loaded
    self.pkMaps = ['Ktrans','Ve','Auc','TTP','MaxSlope']
    self.volumeNodes = {}
    self.refSelectorIgnoreUpdates = False
    self.selectedStudyName = None

  def enter(self):
    settings = qt.QSettings()
    userName = settings.value('PCampReview/UserName')
    resultsLocation = settings.value('PCampReview/ResultsLocation')
    inputLocation = settings.value('PCampReview/InputLocation')
    self.webFormURL = settings.value('PCampReview/webFormURL')

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
    else:
      self.parameters['UserName'] = userName

    if self.webFormURL == None or self.webFormURL == '':
      # prompt the user for the rewview form
      # Note: it is expected that the module uses the form of the structure as
      # in http://goo.gl/nT1z4L. The known structure of the form is used to
      # pre-populate the fields corresponding to readerName, studyName and
      # lesionID.
      self.URLPrompt = qt.QDialog()
      self.URLPromptLayout = qt.QVBoxLayout()
      self.URLPrompt.setLayout(self.URLPromptLayout)
      self.URLLabel = qt.QLabel('Enter review form URL:', self.URLPrompt)
      # replace this if you are using a different form
      self.URLText = qt.QLineEdit('https://docs.google.com/forms/d/1Xwhvjn_HjRJAtgV5VruLCDJ_eyj1C-txi8HWn8VyXa4/viewform')
      self.URLButton = qt.QPushButton('OK', self.URLPrompt)
      self.URLButton.connect('clicked()', self.onURLEntered)
      self.URLPromptLayout.addWidget(self.URLLabel)
      self.URLPromptLayout.addWidget(self.URLText)
      self.URLPromptLayout.addWidget(self.URLButton)
      self.URLPrompt.exec_()

    '''
    # ask where is the input
    if inputLocation == None or inputLocation == '':
      self.dirPrompt = qt.QDialog()
      self.dirPromptLayout = qt.QVBoxLayout()
      self.dirPrompt.setLayout(self.dirPromptLayout)
      self.dirLabel = qt.QLabel('Choose the directory with the input data:', self.dirPrompt)
      self.dirButton = ctk.ctkDirectoryButton(self.dirPrompt)
      self.dirButtonDone = qt.QPushButton('OK', self.dirPrompt)
      self.dirButtonDone.connect('clicked()', self.onInputDirEntered)
      self.dirPromptLayout.addWidget(self.dirLabel)
      self.dirPromptLayout.addWidget(self.dirButton)
      self.dirPromptLayout.addWidget(self.dirButtonDone)
      self.dirPrompt.exec_()
    else:
      self.parameters['InputLocation'] = inputLocation
      print('Setting inputlocation in settings to '+inputLocation)
    # ask where to keep the results
    if resultsLocation == None or resultsLocation == '':
      self.dirPrompt = qt.QDialog()
      self.dirPromptLayout = qt.QVBoxLayout()
      self.dirPrompt.setLayout(self.dirPromptLayout)
      self.dirLabel = qt.QLabel('Choose the directory to store the results:', self.dirPrompt)
      self.dirButton = ctk.ctkDirectoryButton(self.dirPrompt)
      self.dirButtonDone = qt.QPushButton('OK', self.dirPrompt)
      self.dirButtonDone.connect('clicked()', self.onResultsDirEntered)
      self.dirPromptLayout.addWidget(self.dirLabel)
      self.dirPromptLayout.addWidget(self.dirButton)
      self.dirPromptLayout.addWidget(self.dirButtonDone)
      self.dirPrompt.exec_()
    else:
      self.parameters['ResultsLocation'] = resultsLocation
    '''

    self.currentStep = 1

    #self.inputDirLabel.text = self.settings.value('PCampReview/InputLocation')
    #self.resultsDirLabel.text = self.settings.value('PCampReview/ResultsLocation')

  def onNameEntered(self):
    name = self.nameText.text
    if len(name)>0:
      self.settings.setValue('PCampReview/UserName',name)
      self.namePrompt.close()
      self.parameters['UserName'] = name

  def onURLEntered(self):
    url = self.URLText.text
    if len(url)>0:
      self.settings.setValue('PCampReview/webFormURL',url)
      self.URLPrompt.close()
      self.webFormURL = url

  def onResultsDirEntered(self):
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

      self.setOffsetOnAllSliceWidgets(redSliceOffset)

      # set linking properties on one composite node -- should it apply to
      # all?
      sc = redSliceWidget.mrmlSliceCompositeNode()
      sc.SetLinkedControl(1)
      sc.SetInteractionFlags(4+8+16)

      layoutNode.SetViewArrangement(layoutNode.SlicerLayoutUserView)

    # FIXME: look at labelNodes array
    if id == 2:
      layoutNode.SetViewArrangement(layoutNode.SlicerLayoutOneUpRedSliceView)
      if self.refSeriesNumber != '-1':
        ref = self.refSeriesNumber
        redSliceWidget = layoutManager.sliceWidget('Red')
        compositeNode = redSliceWidget.mrmlSliceCompositeNode()
        compositeNode.SetBackgroundVolumeID(self.seriesMap[str(ref)]['Volume'].GetID())
        compositeNode.SetLabelVolumeID(self.seriesMap[str(ref)]['Label'].GetID())
        #slicer.app.applicationLogic().PropagateVolumeSelection(0)
        # redSliceWidget.fitSliceToBackground()

  def studySelected(self, modelIndex):
    print('Row selected: '+self.studiesModel.item(modelIndex.row(),0).text())
    selectionModel = self.studiesView.selectionModel()
    print('Selection model says row is selected: '+str(selectionModel.isRowSelected(modelIndex.row(),qt.QModelIndex())))
    print('Row number: '+str(modelIndex.row()))
    self.selectedStudyName = self.studiesModel.item(modelIndex.row(),0).text()
    self.step2frame.setTitle('Step 2: Study selection (current: '+self.selectedStudyName+')')

  def seriesSelected(self, modelIndex):
    print('Row selected: '+self.seriesModel.item(modelIndex.row(),0).text())
    selectionModel = self.seriesView.selectionModel()
    print('Selection model says row is selected: '+str(selectionModel.isRowSelected(modelIndex.row(),qt.QModelIndex())))
    print('Row number: '+str(modelIndex.row()))

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

  def onQAFormClicked(self):
    self.webView = qt.QWebView()
    self.webView.settings().setAttribute(qt.QWebSettings.DeveloperExtrasEnabled, True)
    self.webView.connect('loadFinished(bool)', self.webViewFormLoadedCallback)
    self.webView.show()
    preFilledURL = self.webFormURL
    preFilledURL += '?entry.1455103354='+self.settings.value('PCampReview/UserName')
    preFilledURL += '&entry.347120626='+self.selectedStudyName
    preFilledURL += '&entry.1734306468='+str(self.editorWidget.toolsColor.colorSpin.value)
    u = qt.QUrl(preFilledURL)
    self.webView.setUrl(u)

  def webViewFormLoadedCallback(self,ok):
    if not ok:
      print('page did not load')
      return
    page = self.webView.page()
    frame = page.mainFrame()
    document = frame.documentElement()
    element = document.findFirst('entry.2057130045')
    element.setAttribute("value", self.parameters['UserName'])

  def onSaveClicked(self):
    """ Elements that will be saved:
        * segmentation: label map
        * w/l for each volume
        Convention: create a directory for each type of resource saved,
        then subdirectory for each scan that was analyzed
    """
    segmentationsDir = self.settings.value('PCampReview/InputLocation')+'/'+self.selectedStudyName+'/Segmentations'
    wlSettingsDir = self.settings.value('PCampReview/InputLocation')+'/'+self.selectedStudyName+'/WindowLevelSettings'
    try:
      os.makedirs(segmentationsDir)
      os.makedirs(wlSettingsDir)
    except:
      print('Failed to create one of the following directories: '+segmentationsDir+' or '+wlSettingsDir)
      pass

    # save all label nodes (there should be only one per volume!)
    labelNodes = slicer.util.getNodes('*-label*')
    print('All label nodes found: '+str(labelNodes))
    savedMessage = 'Segmentations for the following series were saved:\n\n'
    for label in labelNodes.values():

      labelSeries = label.GetName().split(':')[0]
      labelName =  label.GetName().split(':')[1]

      # structure is root -> study -> resources -> series # ->
      # Segmentations/Reconstructions/OncoQuant -> files
      segmentationsDir = self.settings.value('PCampReview/InputLocation')+\
      '/'+self.selectedStudyName+'/RESOURCES/'+labelSeries+'/Segmentations'
      try:
        os.makedirs(segmentationsDir)
      except:
        pass

      import datetime

      structureName = labelName[labelName[:-6].rfind("-")+1:-6]
      # Only save labels with known structure names
      if any(structureName == s for s in self.structureNames):
        print "structure name is:" ,structureName
        uniqueID = self.settings.value('PCampReview/UserName')+\
          '-' + structureName + '-' +\
          datetime.datetime.now().strftime("%Y%m%d%H%M%S")

        labelFileName = os.path.join(segmentationsDir,uniqueID+'.nrrd')

        sNode = slicer.vtkMRMLVolumeArchetypeStorageNode()
        sNode.SetFileName(labelFileName)
        sNode.SetWriteFileFormat('nrrd')
        sNode.SetURI(None)
        success = sNode.WriteData(label)
        if success:
          savedMessage = savedMessage + label.GetName()+'\n'
          print(label.GetName()+' has been saved to '+labelFileName)

    # save w/l settings for all non-label volume nodes
    '''
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
    '''

    self.infoPopup(savedMessage)

  def onInputDirSelected(self):
    self.inputDataDir = qt.QFileDialog.getExistingDirectory(self.parent,'Input data directory', '/Users/fedorov/Temp/XNAT-images')
    self.dataDirButton.text = self.inputDataDir
    self.settings.setValue('PCampReview/InputLocation', self.inputDataDir)
    print('Directory selected:')
    print(self.inputDataDir)
    print(self.settings.value('PCampReview/InputLocation'))

  def onBuildModels(self):
    """make models of the structure label nodesvolume"""
    labelNodes = slicer.util.getNodes('*-label*')

    numNodes = slicer.mrmlScene.GetNumberOfNodesByClass( "vtkMRMLModelHierarchyNode" )
    outHierarchy = None

    for n in xrange(numNodes):
      node = slicer.mrmlScene.GetNthNodeByClass( n, "vtkMRMLModelHierarchyNode" )
      if node.GetName() == "PCampReview Models":
        outHierarchy = node
        break

    # Remove the previous models
    if outHierarchy:
      collection = vtk.vtkCollection()
      outHierarchy.GetChildrenModelNodes(collection)
      n = collection.GetNumberOfItems()
      if n != 0:
        for i in xrange(n):
          modelNode = collection.GetItemAsObject(i)
          slicer.mrmlScene.RemoveNode(modelNode)

    # if models hierarchy does not exist, create it.
    else:
      outHierarchy = slicer.vtkMRMLModelHierarchyNode()
      outHierarchy.SetScene( slicer.mrmlScene )
      outHierarchy.SetName( "PCampReview Models" )
      slicer.mrmlScene.AddNode( outHierarchy )

    progress = qt.QProgressDialog()
    progress.minimumDuration = 0
    progress.modal = True
    progress.show()
    progress.setValue(0)
    progress.setMaximum(len(labelNodes))
    step = 0
    for label in labelNodes.values():
      labelName =  label.GetName().split(':')[1]
      structureName = labelName[labelName[:-6].rfind("-")+1:-6]
      # Only save labels with known structure names
      if any(structureName in s for s in self.structureNames):
        parameters = {}
        parameters["InputVolume"] = label.GetID()
        parameters['FilterType'] = "Sinc"
        parameters['GenerateAll'] = True

        parameters["JointSmoothing"] = False
        parameters["SplitNormals"] = True
        parameters["PointNormals"] = True
        parameters["SkipUnNamed"] = True

        # create models for all labels
        parameters["StartLabel"] = -1
        parameters["EndLabel"] = -1

        parameters["Decimate"] = 0
        parameters["Smooth"] = 0

        parameters["ModelSceneFile"] = outHierarchy

        progress.labelText = '\nMaking Model for %s' % structureName
        progress.setValue(step)
        if progress.wasCanceled:
          break

        try:
          modelMaker = slicer.modules.modelmaker
          self.CLINode = slicer.cli.run(modelMaker, self.CLINode,
                         parameters, wait_for_completion=True)
        except AttributeError:
          qt.QMessageBox.critical(slicer.util.mainWindow(),'Editor', 'The ModelMaker module is not available<p>Perhaps it was disabled in the application settings or did not load correctly.')
      step += 1
    progress.close()
      # 

    if outHierarchy:
      collection = vtk.vtkCollection()
      outHierarchy.GetChildrenModelNodes(collection)
      n = collection.GetNumberOfItems()
      if n != 0:
        for i in xrange(n):
          modelNode = collection.GetItemAsObject(i)
          displayNode = modelNode.GetDisplayNode()
          displayNode.SetSliceIntersectionVisibility(1)
          displayNode.SetSliceIntersectionThickness(2)
        self.modelsVisibilityButton.checked = False
        self.updateViewRenderers()

  def updateViewRenderers (self):
    layoutManager = slicer.app.layoutManager()
    widgetNames = layoutManager.sliceViewNames()
    for wn in widgetNames:
      view = layoutManager.sliceWidget(wn).sliceView()
      view.scheduleRender()

  def setLabelOutline(self, toggled):
    
    # Update button text
    if toggled:
      self.labelMapOutlineButton.setText('Filled')
    else:
      self.labelMapOutlineButton.setText('Outline')

    # Set outline on widgets    
    self.editUtil.setLabelOutline(toggled)
      
    
  def onModelsVisibilityButton(self,toggled):
    outHierarchy = None
    numNodes = slicer.mrmlScene.GetNumberOfNodesByClass( "vtkMRMLModelHierarchyNode" )
    for n in xrange(numNodes):
      node = slicer.mrmlScene.GetNthNodeByClass( n, "vtkMRMLModelHierarchyNode" )
      if node.GetName() == "PCampReview Models":
        outHierarchy = node
        break

    # Remove the previous models
    if outHierarchy:
      collection = vtk.vtkCollection()
      outHierarchy.GetChildrenModelNodes(collection)
      n = collection.GetNumberOfItems()
      if n != 0:
        for i in xrange(n):
          modelNode = collection.GetItemAsObject(i)
          displayNode = modelNode.GetDisplayNode()
          if toggled:
            displayNode.SetSliceIntersectionVisibility(0)
            self.modelsVisibilityButton.setText('Show')
          else:
            displayNode.SetSliceIntersectionVisibility(1)
            self.modelsVisibilityButton.setText('Hide')
        self.updateViewRenderers()

  def findElement(self, dom, name):
    els = dom.getElementsByTagName('element')
    for e in els:
      if e.getAttribute('name') == name:
        return e.childNodes[0].nodeValue

  def getSeriesInfoFromXML(self, f):
    dom = xml.dom.minidom.parse(f)
    number = self.findElement(dom, 'SeriesNumber')
    name = self.findElement(dom, 'SeriesDescription')
    return (number,name)

  def checkAndLoadLabel(self, resourcesDir, seriesNumber, volumeName):
    globPath = os.path.join(self.resourcesDir,str(seriesNumber),"Segmentations",
        self.settings.value('PCampReview/UserName')+'*')
    import glob
    previousSegmentations = glob.glob(globPath)
    if not len(previousSegmentations):
      return (False,None)

    #fileName = previousSegmentations[-1]

    # Iterate over segmentaion files and choose the latest for each structure
    timeStamps = []
    latestSegmentations = {}
    for segmentation in previousSegmentations:
        structureName = segmentation[segmentation.find("-")+1:segmentation.rfind("-")]
        timeStamp = int(segmentation[segmentation.rfind("-")+1:-5])
        if structureName not in latestSegmentations.keys():
          latestSegmentations[structureName] = segmentation
        else:
          storedSegmentation = latestSegmentations[structureName]
          storedTimeStamp = int(storedSegmentation[storedSegmentation.rfind("-")+1:-5])
          if timeStamp > storedTimeStamp:
            latestSegmentations[structureName] = segmentation

    for structure,fileName in latestSegmentations.iteritems():
      (success,label) = slicer.util.loadVolume(fileName, returnNode=True)
      if not success:
        return (False,None)
      print('Setting loaded label name to '+volumeName)
      shortFileName = fileName[fileName.rfind("/")+1:]
      structureID = shortFileName[shortFileName[:-5].find("-")+1:shortFileName[:-5].rfind("-")]
      label.SetName(volumeName+'-'+structureID+'-label')
      label.SetLabelMap(1)
      label.RemoveAllDisplayNodeIDs()

      dNode = slicer.vtkMRMLLabelMapVolumeDisplayNode()
      slicer.mrmlScene.AddNode(dNode)
      dNode.SetAndObserveColorNodeID(self.PCampReviewColorNode.GetID())
      label.SetAndObserveDisplayNodeID(dNode.GetID())

      print('Label loaded, storage node is '+label.GetStorageNode().GetID())

    #return (True,label)
    return True
  '''
  Step 1: Select the directory that has the data
  '''
  def onStep1Selected(self):
    if self.currentStep == 4:
      continuteStep4 = self.showExitStep4Warning()
      if continuteStep4:
        self.step1frame.collapsed = 1
        return

    if self.currentStep == 1:
      return
    self.currentStep = 1
    self.step1frame.collapsed = 0
    self.step2frame.collapsed = 1
    self.step3frame.collapsed = 1
    self.step4frame.collapsed = 1

  '''
  Step 2: Select the patient
  '''
  def onStep2Selected(self):
    if self.currentStep == 4:
      continuteStep4 = self.showExitStep4Warning()
      if continuteStep4:
        self.step2frame.collapsed = 1
        return

    if self.currentStep == 2:
      return

    self.step2frame.setTitle('Step 2: Study selection')

    self.currentStep = 2
    self.step2frame.collapsed = 0
    self.step1frame.collapsed = 1
    self.step3frame.collapsed = 1
    self.step4frame.collapsed = 1

    studyDirs = []
    # get list of studies
    inputDir = self.settings.value('PCampReview/InputLocation')
    if not os.path.exists(inputDir):
      return

    dirs = os.listdir(inputDir)
    for studyName in dirs:
      if os.path.isdir(inputDir+'/'+studyName):
        studyDirs.append(studyName)
        print('Appending '+studyName)

    self.studiesModel.clear()
    self.studyItems = []
    for s in studyDirs:
      sItem = qt.QStandardItem(s)
      self.studyItems.append(sItem)
      self.studiesModel.appendRow(sItem)
      print('Appended to model study '+s)
    # TODO: unload all volume nodes that are already loaded

  '''
  Step 3: Select series of interest
  '''
  def onStep3Selected(self):
    if self.currentStep == 4:
      continuteStep4 = self.showExitStep4Warning()
      if continuteStep4:
        self.step3frame.collapsed = 1
        return

    if self.currentStep == 3 or not self.selectedStudyName:
      self.step3frame.collapsed = 1
      return

    self.currentStep = 3
    print('Entering step 3')

    self.cleanupDir(self.tempDir)

    self.step3frame.collapsed = 0
    self.step2frame.collapsed = 1
    self.step1frame.collapsed = 1
    self.step4frame.collapsed = 1

    # if any volumes have been loaded (we returned back from a previous step)
    # then remove all of them from the scene
    allVolumeNodes = slicer.util.getNodes('vtkMRMLScalarVolumeNode*')
    if len(allVolumeNodes):
      for key in allVolumeNodes.keys():
        slicer.mrmlScene.RemoveNode(allVolumeNodes[key])

    self.parameters['StudyName'] = self.selectedStudyName

    inputDir = self.settings.value('PCampReview/InputLocation')
    self.resourcesDir = os.path.join(inputDir,self.selectedStudyName,'RESOURCES')

    # expect one directory for each processed series, with the name
    # corresponding to the series number
    self.seriesMap = {}
    for root,subdirs,files in os.walk(self.resourcesDir):
      print('Root: '+root+', files: '+str(files))
      resourceType = os.path.split(root)[1]
      print('Resource: '+resourceType)

      if resourceType == 'Reconstructions':
        for f in files:
          print('File: '+f)
          if f.endswith('.xml'):
            metaFile = os.path.join(root,f)
            print('Ends with xml: '+metaFile)
            try:
              (seriesNumber,seriesName) = self.getSeriesInfoFromXML(metaFile)
              print(str(seriesNumber)+' '+seriesName)
            except:
              print('Failed to get from XML')
              continue
            volumePath = os.path.join(root,seriesNumber+'.nrrd')
            self.seriesMap[seriesNumber] = {'MetaInfo':None, 'NRRDLocation':volumePath,'LongName':seriesName}
            self.seriesMap[seriesNumber]['ShortName'] = str(seriesNumber)+":"+seriesName
            # self.helper.abbreviateName(self.seriesMap[seriesNumber]['MetaInfo'])

      # ignore the PK maps for the purposes of segmentation
      if resourceType == 'OncoQuant' and False:
        for f in files:
          if f.endswith('.json'):
            metaFile = open(os.path.join(root,f))
            metaInfo = json.load(metaFile)
            print('JSON meta info: '+str(metaInfo))
            try:
              seriesNumber = metaInfo['SeriesNumber']
              seriesName = metaInfo['SeriesDescription']
            except:
              seriesNumber = metaInfo['DerivedSeriesNumber']
              seriesName = metaInfo['ModelType']+'-'+metaInfo['AIF']+'-'+metaInfo['Parameter']
            volumePath = os.path.join(root,seriesNumber+'.nrrd')
            self.seriesMap[seriesNumber] = {'MetaInfo':metaInfo, 'NRRDLocation':volumePath,'LongName':seriesName}
            self.seriesMap[seriesNumber]['ShortName'] = str(seriesNumber)+":"+self.abbreviateName(self.seriesMap[seriesNumber]['MetaInfo'])

    print('All series found: '+str(self.seriesMap.keys()))

    numbers = [int(x) for x in self.seriesMap.keys()]
    numbers.sort()

    tableItems = []
    for num in numbers:
      desc = self.seriesMap[str(num)]['LongName']
      tableItems.append(str(num)+':'+desc)

    self.seriesModel.clear()
    self.seriesItems = []

    for s in numbers:
      seriesText = str(s)+':'+self.seriesMap[str(s)]['LongName']
      sItem = qt.QStandardItem(seriesText)
      self.seriesItems.append(sItem)
      self.seriesModel.appendRow(sItem)
      sItem.setCheckable(1)
      if self.isSeriesOfInterest(seriesText):
        sItem.setCheckState(2)

  '''
  T2w, sub, ADC, T2map
  '''

  def onStep4Selected(self):
    # set up editor
    if self.currentStep == 4:
      return
    self.currentStep = 4

    self.editorWidget.enter()

    self.step2frame.collapsed = 1
    self.step3frame.collapsed = 1
    self.step1frame.collapsed = 1
    self.step4frame.collapsed = 0

    checkedItems = [x for x in self.seriesItems if x.checkState()]

    # item.CheckState() != 0

    # if no series selected, go to the previous step
    if len(checkedItems) == 0:
      self.onStep3Selected()
      return

    self.volumeNodes = {}
    self.labelNodes = {}
    selectedSeriesNumbers = []
    self.refSeriesNumber = '-1'

    print('Checked items:')
    ref = None

    self.refSelector.clear()

    # reference selector can have None (initially)
    # user should select reference, which triggers creation of the label and
    # initialization of the editor widget

    self.refSelector.addItem('None')

    # ignore refSelector events until the selector is populated!
    self.refSelectorIgnoreUpdates = True

    # iterate over all selected items and add them to the reference selector
    selectedSeries = {}
    for i in checkedItems:
      text = i.text()
      self.delayDisplay('Processing series '+text)

      seriesNumber = text.split(':')[0]
      shortName = self.seriesMap[seriesNumber]['ShortName']
      longName = self.seriesMap[seriesNumber]['LongName']

      fileName = self.seriesMap[seriesNumber]['NRRDLocation']
      (success,volume) = slicer.util.loadVolume(fileName,returnNode=True)
      if success:
        self.seriesMap[seriesNumber]['Volume'] = volume
        volume.SetName(shortName)
        if volume.GetClassName() == 'vtkMRMLMultiVolumeNode':
          d = volume.GetDisplayNode()
          nFrames = volume.GetNumberOfFrames()
          d.SetFrameComponent(nFrames-1)
      else:
        print('Failed to load image volume!')
        return
      success = self.checkAndLoadLabel(self.resourcesDir, seriesNumber, shortName)
      '''
      if success:
        self.seriesMap[seriesNumber]['Label'] = label
      '''

      # cannot use multivolumes as reference, since they are not recognized by
      # Editor
      if volume.GetClassName() == 'vtkMRMLScalarVolumeNode':
        try:
          if self.seriesMap[seriesNumber]['MetaInfo']['ResourceType'] == 'OncoQuant':
            dNode = volume.GetDisplayNode()
            dNode.SetWindowLevel(5.0,2.5)
            dNode.SetAndObserveColorNodeID('vtkMRMLColorTableNodeFileColdToHotRainbow.txt')
          else:
            self.refSelector.addItem(text)
        except:
          self.refSelector.addItem(text)
          pass

      self.seriesMap[seriesNumber]['Volume'].SetName(shortName)

      if longName.find('T2')>=0 and longName.find('AX')>=0:
        ref = int(seriesNumber)

      selectedSeries[seriesNumber] = self.seriesMap[seriesNumber]
      print('Processed '+longName)

      selectedSeriesNumbers.append(int(seriesNumber))

    self.seriesMap = selectedSeries

    print('Selected series: '+str(selectedSeries)+', reference: '+str(ref))
    #self.cvLogic = CompareVolumes.CompareVolumesLogic()
    #self.viewNames = [self.seriesMap[str(ref)]['ShortName']]

    self.refSelectorIgnoreUpdates = False

    self.onReferenceChanged(0)
    self.onViewUpdateRequested(2)
    self.onViewUpdateRequested(1)
    self.setOpacityOnAllSliceWidgets(1.0)

  def showExitStep4Warning(self):
    msgBox = qt.QMessageBox()
    msgBox.setWindowTitle('Warning')
    msgBox.setText('Unsaved contours will be lost!\n Do you still want to exit?')
    msgBox.setStandardButtons(qt.QMessageBox.Yes | qt.QMessageBox.No)
    val = msgBox.exec_()
    if(val == qt.QMessageBox.Yes):
      return False
    else:
      return True

  def onReferenceChanged(self, id):

    if self.refSelectorIgnoreUpdates:
      return
    text = self.refSelector.currentText
    print('Current reference node: '+text)
    if text != 'None' and text != '':
      self.refSeriesNumber = string.split(text,':')[0]
      ref = int(self.refSeriesNumber)
    else:
      return

    print('Reference series selected: '+str(ref))

    # volume nodes ordered by series number
    seriesNumbers= [int(x) for x in self.seriesMap.keys()]
    seriesNumbers.sort()
    self.volumeNodes = [self.seriesMap[str(x)]['Volume'] for x in seriesNumbers if x != ref]
    self.viewNames = [self.seriesMap[str(x)]['ShortName'] for x in seriesNumbers if x != ref]

    self.volumeNodes = [self.seriesMap[str(ref)]['Volume']]+self.volumeNodes
    self.viewNames = [self.seriesMap[str(ref)]['ShortName']]+self.viewNames

    try:
      # check if already have a label for this node
      refLabel = self.seriesMap[str(ref)]['Label']
    except KeyError:
      # create a new label
      labelName = self.seriesMap[str(ref)]['ShortName']+'-label'
      refLabel = self.volumesLogic.CreateAndAddLabelVolume(slicer.mrmlScene,self.volumeNodes[0],labelName)
      self.seriesMap[str(ref)]['Label'] = refLabel

    dNode = refLabel.GetDisplayNode()
    dNode.SetAndObserveColorNodeID(self.PCampReviewColorNode.GetID())
    print('Volume nodes: '+str(self.viewNames))
    self.cvLogic = CompareVolumes.CompareVolumesLogic()

    nVolumeNodes = float(len(self.volumeNodes))
    self.rows = 0
    self.cols = 0
    if nVolumeNodes<=8:
      self.rows = 2 # up to 8
    elif nVolumeNodes>8 and nVolumeNodes<=12:
      self.rows = 3 # up to 12
    elif nVolumeNodes>12 and nVolumeNodes<=16:
      self.rows = 4
    self.cols = math.ceil(nVolumeNodes/self.rows)

    self.editorWidget.setMasterNode(self.volumeNodes[0])
    self.editorWidget.setMergeNode(self.seriesMap[str(ref)]['Label'])

    self.cvLogic.viewerPerVolume(self.volumeNodes, background=self.volumeNodes[0], label=refLabel,layout=[self.rows,self.cols])
    self.cvLogic.rotateToVolumePlanes(self.volumeNodes[0])
    self.editUtil.setLabelOutline(self.labelMapOutlineButton.checked)

    print('Setting master node for the Editor to '+self.volumeNodes[0].GetID())

    self.editorParameterNode.Modified()

    self.onViewUpdateRequested(2)
    self.onViewUpdateRequested(1)
    self.setOpacityOnAllSliceWidgets(1.0)

    print('Exiting onReferenceChanged')

  '''
  def updateViews(self):
    lm = slicer.app.layoutManager()
    w = lm.sliceWidget('Red')
    sl = w.sliceLogic()
    ll = sl.GetLabelLayer()
    lv = ll.GetVolumeNode()
    self.cvLogic.viewerPerVolume(self.volumeNodes, background=self.volumeNodes[0], label=lv, layout=[self.rows,self.cols])

    self.cvLogic.rotateToVolumePlanes(self.volumeNodes[0])
    self.setOpacityOnAllSliceWidgets(1.0)
  '''

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
    import imp, sys, os, slicer, CompareVolumes, string

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
    #seriesItem = mainWidget.seriesTable.widget.item(0,0)
    #seriesItem.setCheckState(1)

    mainWidget.onStep4Selected()
    self.delayDisplay('4')


    self.delayDisplay('Test passed!')
