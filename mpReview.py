from __future__ import division
import os, json, xml.dom.minidom, string, glob, re, math
import vtk, qt, ctk, slicer
import logging
import CompareVolumes
import SimpleITK as sitk
import sitkUtils
import datetime
from slicer.ScriptedLoadableModule import *

from mpReviewPreprocessor import mpReviewPreprocessorLogic

from qSlicerMultiVolumeExplorerModuleWidget import qSlicerMultiVolumeExplorerSimplifiedModuleWidget
from qSlicerMultiVolumeExplorerModuleHelper import qSlicerMultiVolumeExplorerModuleHelper as MVHelper

from SlicerDevelopmentToolboxUtils.mixins import ModuleWidgetMixin, ModuleLogicMixin
from SlicerDevelopmentToolboxUtils.helpers import WatchBoxAttribute
from SlicerDevelopmentToolboxUtils.widgets import TargetCreationWidget, XMLBasedInformationWatchBox
from SlicerDevelopmentToolboxUtils.icons import Icons

from DICOMLib import DICOMPlugin
import DICOMSegmentationPlugin

import DICOMwebBrowser
from DICOMwebBrowser import GoogleCloudPlatform

import hashlib 
import pydicom 
# from builtins import False


import shutil





class GoogleCloudPlatform(object):

  def gcloud(self, subcommand):

    import shutil 
    args = [shutil.which('gcloud')]
    if (None in args):
      logging.error(f"Unable to locate gcloud, please install the Google Cloud SDK")
    args.extend(subcommand.split())
    process = slicer.util.launchConsoleProcess(args)
    process.wait()
    return process.stdout.read()

  def projects(self):
    return sorted(self.gcloud("projects list --sort-by=projectId --format=value(PROJECT_ID)").split("\n"), key=str.lower)

  def datasets(self, project):
    return sorted(self.gcloud(f"--project {project} healthcare datasets list --format=value(ID,LOCATION)").split("\n"), key=str.lower)

  def dicomStores(self, project, dataset):
    return sorted(self.gcloud(f"--project {project} healthcare dicom-stores list --dataset {dataset} --format=value(ID)").split("\n"), key=str.lower)

  def token(self):
    return self.gcloud("auth print-access-token").strip()

  def copy_from_bucket_to_dicomStore(self, project, location, dataset, dicomStore, bucket_name):
    return self.gcloud(f"--project {project} healthcare dicom-stores import gcs {dicomStore} --dataset {dataset} --location {location} --gcs-uri gs://{bucket_name}/**.dcm")

  def datasetsOnly(self, project):
    return self.gcloud(f"--project {project} healthcare datasets list --format=value(ID)").split("\n")

  def locations(self):
    return self.gcloud(f"compute regions list --format=value(NAME)").split("\n")

  def create_dicomStore(self, project, location, dataset, dicomStore):
    return sorted(self.gcloud(f"--project {project} healthcare dicom-stores create {dicomStore} --dataset {dataset} --format=value(ID)").split("\n"), key=str.lower)




class mpReview(ScriptedLoadableModule, ModuleWidgetMixin):

  def __init__(self, parent):
    ScriptedLoadableModule.__init__(self, parent)
    parent.title = "mpReview"
    parent.categories = ["Informatics"]
    parent.dependencies = ["SlicerDevelopmentToolbox"]
    parent.contributors = ["Andrey Fedorov (SPL)", "Robin Weiss (U. of Chicago)", "Alireza Mehrtash (SPL)",
                           "Christian Herz (SPL)"]
    parent.helpText = """
    Multiparametric Image Review (mpReview) module is intended to support review and annotation of multiparametric
    image data. The driving use case for the development of this module was review and segmentation of the regions of
    interest in prostate cancer multiparametric MRI.
    """
    parent.acknowledgementText = """
    Supported by NIH U24 CA180918 (PIs Fedorov & Kikinis) and U01CA151261 (PI Fennessy)
    """ # replace with organization, grant and thanks.
    self.parent = parent

    # Add this test to the SelfTest module's list for discovery when the module
    # is created.  Since this module may be discovered before SelfTests itself,
    # create the list if it doesn't already exist.
    try:
      slicer.selfTests
    except AttributeError:
      slicer.selfTests = {}

  def runTest(self):
    return


class mpReviewWidget(ScriptedLoadableModuleWidget, ModuleWidgetMixin):

  PIRADS_VIEWFORM_URL = 'https://docs.google.com/forms/d/1Xwhvjn_HjRJAtgV5VruLCDJ_eyj1C-txi8HWn8VyXa4/viewform'
  QA_VIEWFORM_URL = 'https://docs.google.com/forms/d/18Ni2rcooi60fev5mWshJA0yaCzHYvmXPhcG2-jMF-uw/viewform'

  @property
  def inputDataDir(self):
    return self.dataDirButton.directory

  @inputDataDir.setter
  def inputDataDir(self, directory):
    logging.debug('Directory selected: %s' % directory)
    if not os.path.exists(directory):
      directory = None
      self.dataDirButton.text = "Choose data directory"
      truncatedPath = None
    else:
      truncatedPath = ModuleLogicMixin.truncatePath(directory)
      self.dataDirButton.text = truncatedPath
      self.dataDirButton.caption = directory
      self.setSetting('InputLocation', directory)
      self.checkAndSetLUT()
      self.updateStudyTable()
    self.informationWatchBox.setInformation("CurrentDataDir", truncatedPath, toolTip=directory)

  def __init__(self, parent = None):
    ScriptedLoadableModuleWidget.__init__(self, parent)
    self.resourcesPath = os.path.join(slicer.modules.mpreview.path.replace(self.moduleName+".py",""), 'Resources')
    self.qaFormURL = ''
    self.piradsFormURL = ''

    # mrml node for invoking command line modules
    self.CLINode = None
    self.logic = mpReviewLogic()
    self.multiVolumeExplorer = None

    # set up temporary directory
    self.tempDir = os.path.join(slicer.app.temporaryPath, 'mpReview-tmp')
    self.logic.createDirectory(self.tempDir, message='Temporary directory location: ' + self.tempDir)
    self.modulePath = os.path.dirname(slicer.util.modulePath(self.moduleName))

  def getAllSliceWidgets(self):
    widgetNames = self.layoutManager.sliceViewNames()
    return [self.layoutManager.sliceWidget(wn) for wn in widgetNames]

  def setOffsetOnAllSliceWidgets(self, offset):
    for widget in self.getAllSliceWidgets():
      node = widget.mrmlSliceNode()
      node.SetSliceOffset(offset)

  def linkAllSliceWidgets(self, link):
    for widget in self.getAllSliceWidgets():
      sc = widget.mrmlSliceCompositeNode()
      sc.SetLinkedControl(link)
      sc.SetInteractionFlagsModifier(4+8+16)

  def setOpacityOnAllSliceWidgets(self, opacity):
    for widget in self.getAllSliceWidgets():
      sc = widget.mrmlSliceCompositeNode()
      sc.SetForegroundOpacity(opacity)

  def updateViewRenderer (self):
    for widget in self.getAllSliceWidgets():
      view = widget.sliceView()
      view.scheduleRender()

  def setupIcons(self):
    self.databaseSelectionIcon = self.createIcon('icon-databaseselection_fit.png') # fix later
    self.studySelectionIcon = self.createIcon('icon-studyselection_fit.png')
    self.segmentationIcon = self.createIcon('icon-segmentation_fit.png')
    self.completionIcon = self.createIcon('icon-completion_fit.png')

  def setupTabBarNavigation(self):
    self.tabWidget = qt.QTabWidget()
    self.layout.addWidget(self.tabWidget)

    self.databaseSelectionWidget = qt.QWidget() # added
    self.studyAndSeriesSelectionWidget = qt.QWidget()
    self.segmentationWidget = qt.QWidget()
    self.completionWidget = qt.QWidget()

    self.databaseSelectionWidgetLayout = qt.QGridLayout() # added
    self.studyAndSeriesSelectionWidgetLayout = qt.QGridLayout()
    self.segmentationWidgetLayout = qt.QVBoxLayout()
    self.completionWidgetLayout = qt.QFormLayout()

    self.databaseSelectionWidget.setLayout(self.databaseSelectionWidgetLayout) # added
    self.studyAndSeriesSelectionWidget.setLayout(self.studyAndSeriesSelectionWidgetLayout)
    self.segmentationWidget.setLayout(self.segmentationWidgetLayout)
    self.completionWidget.setLayout(self.completionWidgetLayout)

    self.tabWidget.setIconSize(qt.QSize(85, 30))

    self.tabWidget.addTab(self.databaseSelectionWidget, self.databaseSelectionIcon, '')  
    self.tabWidget.addTab(self.studyAndSeriesSelectionWidget, self.studySelectionIcon, '')
    self.tabWidget.addTab(self.segmentationWidget, self.segmentationIcon, '')
    self.tabWidget.addTab(self.completionWidget, self.completionIcon, '')

    # self.setTabsEnabled([1,2], False)
    self.setTabsEnabled([1,2,3], False)

  def onTabWidgetClicked(self, currentIndex):
    if self.currentTabIndex == currentIndex:
      return
    setNewIndex = False
    # if currentIndex == 0:
    #   setNewIndex = self.onStep1Selected()
    # if currentIndex == 1:
    #   setNewIndex = self.onStep2Selected()
    # if currentIndex == 2:
    #   setNewIndex = self.onStep3Selected()
    # if setNewIndex:
    #   self.currentTabIndex = currentIndex
    #
    # if currentIndex == 2:
    #   self.editorWidget.installKeyboardShortcuts()
    # else:
    #   self.editorWidget.setActiveEffect(None)
    #   self.editorWidget.uninstallKeyboardShortcuts()
    #   self.editorWidget.removeViewObservations()
    
    if currentIndex == 0:
      setNewIndex = self.onStep0Selected() # database 
    if currentIndex == 1:
      setNewIndex = self.onStep1Selected() # studies 
    if currentIndex == 2:
      setNewIndex = self.onStep2Selected() # series
    if currentIndex == 3: 
      setNewIndex = self.onStep3Selected() # segmentation tab 
    if setNewIndex:
      self.currentTabIndex = currentIndex

    if currentIndex == 3: # if series selected, can view segmentation tab  
      self.editorWidget.installKeyboardShortcuts()
    else:
      self.editorWidget.setActiveEffect(None)
      self.editorWidget.uninstallKeyboardShortcuts()
      self.editorWidget.removeViewObservations()
    

  def setup(self):
    ScriptedLoadableModuleWidget.setup(self)

    self.setupIcons()
    self.setupInformationFrame()
    self.setupTabBarNavigation()

    self.parameters = {}

    self.crosshairNode = slicer.mrmlScene.GetNthNodeByClass(0, 'vtkMRMLCrosshairNode')
    
    self.setupDatabaseSelectionUI()
    self.setupDataAndStudySelectionUI()
    self.setupSeriesSelectionView()
    self.setupSegmentationToolsUI()
    self.setupCompletionUI()
    self.setupConnections()
    # self.layout.addStretch(1)

    self.volumesLogic = slicer.modules.volumes.logic()

    # these are the PK maps that should be loaded
    self.pkMaps = ['Ktrans','Ve','Auc','TTP','MaxSlope']
    self.volumeNodes = {}
    self.refSelectorIgnoreUpdates = False
    self.selectedStudyName = None

    # self.dataDirButton.directory = self.getSetting('InputLocation')
    self.currentTabIndex = 0
    
    # self.updateStudyTable() # I added
    
    self.checkAndSetLUT() # I added 

  def setupInformationFrame(self):

    watchBoxInformation = [WatchBoxAttribute('StudyID', 'Study ID:'),
                           WatchBoxAttribute('PatientName', 'Name:', 'PatientName'),
                           WatchBoxAttribute('StudyDate', 'Study Date:', 'StudyDate'),
                           WatchBoxAttribute('PatientID', 'PID:', 'PatientID'),
                           WatchBoxAttribute('CurrentDataDir', 'Current Data Dir:'),
                           WatchBoxAttribute('PatientBirthDate', 'DOB:', 'PatientBirthDate')]

    self.informationWatchBox = XMLBasedInformationWatchBox(watchBoxInformation, columns=2)

    self.layout.addWidget(self.informationWatchBox)
    
  def setupDatabaseSelectionUI(self):
    
    self.setupDatabaseSelectionView()
    
  def setupDatabaseSelectionView(self):
    
    self.databaseGroupBox = qt.QGroupBox("Databases")
    databaseGroupBoxLayout = qt.QFormLayout()
    
    self.selectLocalDatabaseButton = qt.QRadioButton('Use local database')
    self.selectRemoteDatabaseButton = qt.QRadioButton('Use GCP remote server')
    self.selectOtherRemoteDatabaseButton = qt.QRadioButton('Use other remote server')
    
    # self.gcp = DICOMwebBrowser.GoogleCloudPlatform() # this doesn't work, why?  
    # self.gcp = GoogleCloudPlatform() # this works 
    
    databaseGroupBoxLayout.addRow(self.selectLocalDatabaseButton)
    databaseGroupBoxLayout.addRow(self.selectRemoteDatabaseButton)
    
    self.projectSelectorCombobox = qt.QComboBox()
    databaseGroupBoxLayout.addRow("Project: ", self.projectSelectorCombobox)
    # self.projectSelectorCombobox.addItems(self.gcp.projects())
    self.projectSelectorCombobox.connect("currentIndexChanged(int)", self.onProjectSelected)
    self.projectSelectorCombobox.setEnabled(False)
    
    # project_list = self.gcp.projects()
    # self.projectCompleter = qt.QCompleter(project_list)
    # self.projectCompleter.setCaseSensitivity(0)
    # self.projectCompleter.setCompletionColumn(0)
    # self.projectSelectorCombobox.setCompleter(self.projectCompleter)
    
    self.datasetSelectorCombobox = qt.QComboBox()
    databaseGroupBoxLayout.addRow("Dataset: ", self.datasetSelectorCombobox)
    self.datasetSelectorCombobox.connect("currentIndexChanged(int)", self.onDatasetSelected)
    self.datasetSelectorCombobox.setEnabled(False)

    self.dicomStoreSelectorCombobox = qt.QComboBox()
    databaseGroupBoxLayout.addRow("DICOM Store: ", self.dicomStoreSelectorCombobox)
    self.dicomStoreSelectorCombobox.connect("currentIndexChanged(int)", self.onDICOMStoreSelected)
    self.dicomStoreSelectorCombobox.setEnabled(False)
    
    self.serverUrlLineEdit = qt.QLineEdit()
    databaseGroupBoxLayout.addRow("GCP Server URL: ", self.serverUrlLineEdit)
    self.serverUrlLineEdit.setText('')
    self.serverUrlLineEdit.setReadOnly(True)
    
    self.selectDatabaseOKButton = qt.QPushButton("OK")
    self.selectDatabaseOKButton.setEnabled(False)
    databaseGroupBoxLayout.addRow(self.selectDatabaseOKButton)
    
    # Other remote 
    # databaseGroupBoxLayout.setVerticalSpacing(10) # this sets for all. 
    databaseGroupBoxLayout.addRow(self.selectOtherRemoteDatabaseButton)
    
    self.OtherserverUrlLineEdit = qt.QLineEdit()
    databaseGroupBoxLayout.addRow("Other Server URL: ", self.OtherserverUrlLineEdit)
    self.OtherserverUrlLineEdit.setText('')
    self.OtherserverUrlLineEdit.setReadOnly(True)
    
    self.selectOtherRemoteDatabaseOKButton = qt.QPushButton("OK")
    self.selectOtherRemoteDatabaseOKButton.setEnabled(False)
    databaseGroupBoxLayout.addRow(self.selectOtherRemoteDatabaseOKButton)
    
    self.databaseGroupBox.setLayout(databaseGroupBoxLayout)
    self.databaseSelectionWidgetLayout.addWidget(self.databaseGroupBox, 3, 0, 1, 3)
    
    
    # # this works below for listing projects.
    # args = ['C:\\Users\\deepa\\AppData\\Local\\Google\\Cloud SDK\\google-cloud-sdk\\bin\\gcloud.CMD', 'projects', 'list', '--format=value(PROJECT_ID)']
    # process = slicer.util.launchConsoleProcess(args)
    # process.stdout.read()
    
  def getServerUrl(self):

    if hasattr(self,'dicomStore'):
      url = "https://healthcare.googleapis.com/v1beta1"
      url += f"/projects/{self.project}"
      url += f"/locations/{self.location}"
      url += f"/datasets/{self.dataset}"
      url += f"/dicomStores/{self.dicomStore}"
      url += "/dicomWeb"
    else:
      # url = ''
      url = self.serverUrlLineEdit.text
    
    self.serverUrl = url
  
    
  def onProjectSelected(self):
    currentText = self.projectSelectorCombobox.currentText
    if currentText != "":
      self.project = currentText.split()[0]
      self.datasetSelectorCombobox.clear()
      self.dicomStoreSelectorCombobox.clear()
      qt.QTimer.singleShot(0, lambda : self.datasetSelectorCombobox.addItems(self.gcp.datasets(self.project)))
      
      self.datasetSelectorCombobox.setEditable(True)
      dataset_list = self.gcp.datasets(self.project)
      self.datasetCompleter = qt.QCompleter(dataset_list)
      self.datasetCompleter.setCaseSensitivity(0)
      self.datasetCompleter.setCompletionColumn(0)
      self.datasetSelectorCombobox.setCompleter(self.datasetCompleter)
    
      
  def onDatasetSelected(self):
    currentText = self.datasetSelectorCombobox.currentText
    if currentText != "":
      datasetTextList = currentText.split()
      self.dataset = datasetTextList[0]
      self.location = datasetTextList[1]
      self.dicomStoreSelectorCombobox.clear()
      qt.QTimer.singleShot(0, lambda : self.dicomStoreSelectorCombobox.addItems(self.gcp.dicomStores(self.project, self.dataset)))
      
      self.dicomStoreSelectorCombobox.setEditable(True)
      dicomStore_list = self.gcp.dicomStores(self.project, self.dataset)
      self.dicomStoreCompleter = qt.QCompleter(dicomStore_list)
      self.dicomStoreCompleter.setCaseSensitivity(0)
      self.dicomStoreCompleter.setCompletionColumn(0)
      self.dicomStoreSelectorCombobox.setCompleter(self.dicomStoreCompleter)

  # def onDICOMStoreSelected(self):
  #   currentText = self.dicomStoreSelectorCombobox.currentText
  #   if currentText != "":
  #     self.dicomStore = currentText.split()[0]
  #     # populate the server url here?? 
  #     self.getServerUrl()
  #     self.serverUrlLineEdit.setText(self.serverUrl)
  #     # authorize 
  #     self.dicomwebAuthorize()
  #     # fill the studies 
  #     self.studiesMap = {} 
  #     self.getStudyNamesRemoteDatabase()      
  #     self.fillStudyTableRemoteDatabase()
  #
  #     # update the availability of the next tab 
  #     self.updateStudiesAndSeriesTabAvailability()

  def onDICOMStoreSelected(self):
    currentText = self.dicomStoreSelectorCombobox.currentText
    if currentText != "":
      self.dicomStore = currentText.split()[0]
      # populate the server url here
      self.getServerUrl()
      self.serverUrlLineEdit.setText(self.serverUrl)
      self.selectDatabaseOKButton.setEnabled(True)

      
  def onDICOMStoreChangedMessageBox(self):
    
    mbox = qt.QMessageBox()
    mbox.text = self.messageBoxText 
    okButton = mbox.addButton(qt.QMessageBox.Ok)
    mbox.exec_()
    selectedButton = mbox.clickedButton()
    # if selectedButton in [okButton]:
  
  def checkIfProjectExists(self):
     
    projectList = self.gcp.projects()
    if not self.project in projectList: 
      return False 
    else: 
      return True 
    
  def checkIfLocationExists(self):
    
    locationList = self.gcp.locations()
    if not self.location in locationlist: 
      return False
    else:
      return True 
    
  def checkIfDatasetExists(self):
    
    # datasetList = self.gcp.datasets(self.project)
    datasetList = self.gcp.datasetsOnly(self.project)
    if not self.dataset in datasetList:
      return False
    else: 
      return True 
    
  def checkIfDicomStoreExists(self):
    
    dicomStoreList = self.gcp.dicomStores(self.project, self.dataset)
    if not self.dicomStore in dicomStoreList: 
      return False 
    else:
      return True 
    
  def checkserverURLIsValid(self):
    
    # set to True at beginning 
    self.serverURLIsValid = True
    
    # get the current text  
    currentText = self.serverUrlLineEdit.text 
    textparts = currentText.split('/')
    
    # Need to check if first part of url is also valid. https://healthcare.googleapis.com/v1beta1
    startStr = r"https://healthcare.googleapis.com/v1beta1"
    if not startStr in currentText: 
      self.messageBoxText = 'Beginning of serverURL must be set to https://healthcare.googleapis.com/v1beta1'
      self.serverURLIsValid = False 
      return 
      
    # If 'project' is in the serverURL 
    if 'projects' in textparts: 
      project_ind = textparts.index('projects')
      self.project = textparts[project_ind+1]
      # Check if the project exists 
      if not self.checkIfProjectExists(): 
        self.messageBoxText = 'Project ' + self.project + ' does not exist, please specify another one.'
        self.serverURLIsValid = False 
        return 
    else: 
      self.messageBoxText = 'Keyword project must exist in the serverURL.' 
      self.serverURLIsValid = False 
      return 
    
    # If 'location' is in serverURL
    if 'location' in textparts: 
      location_ind = textparts.index('location')
      self.location = textparts[location_ind+1]
      # Check if location is valid 
      if not self.checkIfLocationExists():
        self.messageBox = 'Location ' + self.location + ' is not a valid location, please specify another one.'
        self.serverURLIsValid = False
        return 
      else:
        self.messageBoxText = 'Keyword location must exist in the serverURL.'
        self.serverURLIsValid = False 
        return 

    # If 'dataset' is in serverURL 
    if 'datasets' in textparts:  
      dataset_ind = textparts.index('datasets')
      self.dataset = textparts[dataset_ind+1]
      # Check if dataset exists in the project 
      if not self.checkIfDatasetExists():
        self.messageBoxText = 'Dataset ' + self.dataset + ' does not exist within project ' + self.project + ', please specify another one.'
        self.serverURLIsValid = False 
        return 
    else: 
      self.messageBoxText = 'Keyword dataset must exist in the serverURL.'
      self.serverURLIsValid = False 
      return 
    
    # If 'dicomStores' is in serverURL
    if 'dicomStores' in textparts: 
      dicomStore_ind = textparts.index('dicomStores')
      self.dicomStore = textparts[dicomStore_ind+1]
      # Check if dicomStore exists in the project and dataset 
      if not self.checkIfDicomStoreExists():
        self.messageBoxText = 'dicomStore ' + self.dicomStore + ' does not exist within project ' + self.project + ' nor within dataset ' + self.dataset + ', please specify another one.'
        self.serverURLIsValid = False 
        return 
    else: 
      self.messageBoxText = 'Keyword dicomStores must exist in the serverURL. '
      self.serverURLIsValid = False 
      return 
  
    
  
  # If the serverURL is changed, set the project/dataset/dicom datastore. 
  # Do error checking too. 
  # https://healthcare.googleapis.com/v1beta1/projects/idc-external-018/locations/us-central1/datasets/mpreview_dataset/dicomStores/mpreview_dicomstore/dicomWeb
  def onDICOMStoreChanged(self):
    
    # get error message 
    errorMessage = self.checkserverURLIsValid() # this sets the self.serverURLIsValid field 
    # If valid, set the new serverURL so we can get the updated studies 
    # And then update the study table remote 
    if self.serverURLIsValid:
      self.getServerUrl()
      self.updateStudyTableRemote()
    # If not valid, display an error message 
    else:
      self.onDICOMStoreChangedMessageBox()
      self.setTabsEnabled([1,2], False) # set the study tab and segmentation tab to false.
    

    # self.getServerUrl()
    # self.updateStudyTableRemote()
    
    return 
  
  def onURLEdited(self):
    
    print ('server url text changed')
    self.serverUrl = self.serverUrlLineEdit.text
    print (self.serverUrl)
    
    return 
    
  def onOtherURLEdited(self):
    
    print ('other server url text changed')
    self.otherserverUrl = self.OtherserverUrlLineEdit.text
    print (self.otherserverUrl)
    
    return 
      
  def updateStudiesAndSeriesTabAvailability(self):
    self.setTabsEnabled([1], True)
    
      
  # Will add in more error checking for importing packages later 
  def dicomwebAuthorize(self):
    import dicomweb_client.log
    dicomweb_client.log.configure_logging(2)
    from dicomweb_client.api import DICOMwebClient
    effectiveServerUrl = self.serverUrl
    
    # print ('effectiveServerUrl: ' + str(effectiveServerUrl))
    
    session = None
    headers = {}
    headers["Authorization"] = f"Bearer {GoogleCloudPlatform().token()}"
    self.DICOMwebClient = DICOMwebClient(url=effectiveServerUrl, session=session, headers=headers)
      
  # def listStudies(self):
  #   offset = 0 
  #   studies = [] 
  #   while True:
  #     subset = self.DICOMwebClient.search_for_studies(offset=offset)
  #     if len(subset) == 0:
  #       break
  #     if subset[0] in studies:
  #       # got the same study twice, so probably this server does not respect offset,
  #       # therefore we cannot do paging
  #       break
  #     studies.extend(subset)
  #     offset += len(subset)
  #
  #   self.studies = studies 
  #
  #   print ('studies: ' + str(studies))
  

  def dicomwebOtherAuthorize(self):
    import dicomweb_client.log 
    dicomweb_client.log.configure_logging(2)
    from dicomweb_client.api import DICOMwebClient
    effectiveServerUrl = self.otherserverUrl 
    
    session = None
    self.DICOMwebClient = DICOMwebClient(url=effectiveServerUrl, session=session)
    
  def setupGoogleCloudPlatform(self):
  #
  #   import shutil 
  #   args = [shutil.which('gcloud')]
  #   if (None in args):
  #     logging.error(f"Unable to locate gcloud, please install the Google Cloud SDK")
  #   args.extend(subcommand.split())
  #   process = slicer.util.launchConsoleProcess(args)
  #   process.wait()
  #   return process.stdout.read()
  
    # print('trying to use class from DICOMwebBrowser')
    self.gcp = GoogleCloudPlatform()
    # self.gcp = DICOMwebBrowser.GoogleCloudPlatform()
    print('projects: ' + str(self.gcp.projects()))
      
    self.projectSelectorCombobox.addItems(self.gcp.projects())
    
    project_list = self.gcp.projects()
    self.projectCompleter = qt.QCompleter(project_list)
    self.projectCompleter.setCaseSensitivity(0)
    self.projectCompleter.setCompletionColumn(0)
    self.projectSelectorCombobox.setCompleter(self.projectCompleter)
      

  def onCancel(self):
    self.projectSelectorCombobox.clear()
    self.datasetSelectorCombobox.clear()
    self.dicomStoreSelectorCombobox.clear()


  def setupDataAndStudySelectionUI(self):
    # self.dataDirButton = ctk.ctkDirectoryButton()
    # self.studyAndSeriesSelectionWidgetLayout.addWidget(qt.QLabel("Data directory:"), 0, 0, 1, 1)
    # self.studyAndSeriesSelectionWidgetLayout.addWidget(self.dataDirButton, 0, 1, 1, 2)

    # print ('in setupDataAndStudySelectionUI')
    self.customLUTInfoIcon = self.createHelperLabel()
    self.studyAndSeriesSelectionWidgetLayout.addWidget(self.customLUTInfoIcon, 0, 2, 1, 1, qt.Qt.AlignRight)
    self.customLUTInfoIcon.hide()
    self.setupStudySelectionView()

  def createHelperLabel(self, toolTipText=""):
    label = self.createLabel("", pixmap=Icons.info.pixmap(qt.QSize(23, 20)), toolTip=toolTipText)
    label.setCursor(qt.Qt.PointingHandCursor)
    return label

  def setupStudySelectionView(self):
    self.studiesGroupBox = ctk.ctkCollapsibleGroupBox()
    self.studiesGroupBox.title = "Studies"
    studiesGroupBoxLayout = qt.QGridLayout()
    self.studiesGroupBox.setLayout(studiesGroupBoxLayout)
    self.studiesView, self.studiesModel = self.createListView('StudiesTable', ['Study ID'])
    self.studiesView.setSizePolicy(qt.QSizePolicy.Expanding, qt.QSizePolicy.Expanding)
    
    filter_proxy_model = qt.QSortFilterProxyModel()
    filter_proxy_model.setSourceModel(self.studiesModel)
    # filter_proxy_model.setSourceModel(self.studiesView.selectionModel())
    filter_proxy_model.setFilterKeyColumn(1)
    
    self.studiesFilterLine = qt.QLineEdit()
    self.studiesFilterLine.textChanged.connect(filter_proxy_model.setFilterRegExp)
    studiesGroupBoxLayout.addWidget(self.studiesFilterLine)
    
    studiesGroupBoxLayout.addWidget(self.studiesView)
    
    self.studyAndSeriesSelectionWidgetLayout.addWidget(self.studiesGroupBox, 2, 0, 1, 3)

  def setupSeriesSelectionView(self):
    self.seriesGroupBox = qt.QGroupBox("Series")
    seriesGroupBoxLayout = qt.QGridLayout()
    self.seriesGroupBox.setLayout(seriesGroupBoxLayout)
    self.seriesView, self.seriesModel = self.createListView('SeriesTable', ['Series ID'])
    self.seriesView.setSelectionMode(qt.QAbstractItemView.ExtendedSelection)
    self.selectAllSeriesButton = self.createButton('Select All')
    self.deselectAllSeriesButton = self.createButton('Deselect All')
    self.selectAllSeriesButton.setEnabled(False)
    self.deselectAllSeriesButton.setEnabled(False)
    seriesGroupBoxLayout.addWidget(self.seriesView, 0, 0, 1, 2)
    seriesGroupBoxLayout.addWidget(self.createHLayout([self.selectAllSeriesButton,  self.deselectAllSeriesButton]),
                                   1, 0, 1, 2)
    self.studyAndSeriesSelectionWidgetLayout.addWidget(self.seriesGroupBox, 3, 0, 1, 3)

  def setupSegmentationToolsUI(self):
    self.refSelector = qt.QComboBox()
    self.segmentationWidgetLayout.addWidget(self.createHLayout([qt.QLabel("Reference image: "), self.refSelector]))
    self.setupMultiVolumeExplorerUI()
    self.setupLabelMapEditorUI()
    self.setupAdvancedSegmentationSettingsUI()
    self.setupFiducialsUI()
    # keep here names of the views created by CompareVolumes logic
    self.viewNames = []
    self.segmentationWidgetLayout.addStretch(1)

  def setupMultiVolumeExplorerUI(self):
    self.multiVolumeExplorerArea = ctk.ctkCollapsibleButton()
    self.multiVolumeExplorerArea.text = "MultiVolumeExplorer"
    self.multiVolumeExplorerArea.collapsed = True
    self.multiVolumeExplorer = mpReviewMultiVolumeExplorer(qt.QFormLayout(self.multiVolumeExplorerArea))
    self.multiVolumeExplorer.setup()
    self.segmentationWidgetLayout.addWidget(self.multiVolumeExplorerArea)

  def setupLabelMapEditorUI(self):

    self.editorWidget = slicer.qMRMLSegmentEditorWidget()
    self.editorWidget.defaultTerminologyEntrySettingsKey = "mpReview/DefaultTerminologyEntry"
    self.editorWidget.setMaximumNumberOfUndoStates(10)
    self.editorWidget.setMRMLScene(slicer.mrmlScene)
    self.editorWidget.unorderedEffectsVisible = False
    self.editorWidget.setEffectNameOrder(["Paint", "Draw", "Erase", "Fill between slices", "Margin"])
    self.editorWidget.jumpToSelectedSegmentEnabled = True
    self.editorWidget.switchToSegmentationsButtonVisible = False
    # added
    self.editorWidget.setMasterVolumeNodeSelectorVisible(False)
    self.editorWidget.setSegmentationNodeSelectorVisible(False)

    # Select parameter set node if one is found in the scene, and create one otherwise
    segmentEditorSingletonTag = "mpReviewSegmentEditor"
    segmentEditorNode = slicer.mrmlScene.GetSingletonNode(segmentEditorSingletonTag, "vtkMRMLSegmentEditorNode")
    if segmentEditorNode is None:
      segmentEditorNode = slicer.vtkMRMLSegmentEditorNode()
      segmentEditorNode.SetSingletonTag(segmentEditorSingletonTag)
      # Set overwrite mode: 0/1/2 -> overwrite all/visible/none
      segmentEditorNode.SetOverwriteMode(2) # allow overlap
      segmentEditorNode = slicer.mrmlScene.AddNode(segmentEditorNode)
    if self.editorWidget.mrmlSegmentEditorNode() != segmentEditorNode:
      self.editorWidget.setMRMLSegmentEditorNode(segmentEditorNode)

    self.segmentationWidgetLayout.addWidget(self.editorWidget)

    self.modelsVisibilityButton = self.createButton('Hide', checkable=True)
    self.labelMapVisibilityButton = self.createButton('Hide', checkable=True)
    self.labelMapOutlineButton = self.createButton('Outline', checkable=True)
    self.enableJumpToROI = qt.QCheckBox("Jump to ROI")
    self.enableJumpToROI.checked = self.editorWidget.jumpToSelectedSegmentEnabled
    modelsFrame = self.createHLayout([qt.QLabel('Structure Models: '),
                                      self.modelsVisibilityButton, self.labelMapVisibilityButton,
                                      self.labelMapOutlineButton, self.enableJumpToROI])
    # added
    self.modelsVisibilityButton.hide() 
    
    self.segmentationWidgetLayout.addWidget(modelsFrame)

  def setupAdvancedSegmentationSettingsUI(self):
    self.advancedSettingsArea = ctk.ctkCollapsibleButton()
    self.advancedSettingsArea.text = "Advanced Settings"
    self.advancedSettingsArea.collapsed = True

    self.setupSingleMultiViewSettingsUI()
    self.setupViewerOrientationSettingsUI()

    advancedSettingsLayout = qt.QFormLayout(self.advancedSettingsArea)
    advancedSettingsLayout.addRow("Show series: ", self.groupWidget)
    advancedSettingsLayout.addRow('View orientation: ', self.orientationBox)
    self.segmentationWidgetLayout.addWidget(self.advancedSettingsArea)

  def setupSingleMultiViewSettingsUI(self):
    self.multiView = qt.QRadioButton('All')
    self.singleView = qt.QRadioButton('Reference only')
    self.multiView.setChecked(True)
    self.groupWidget = qt.QGroupBox()
    self.groupLayout = qt.QFormLayout(self.groupWidget)
    self.groupLayout.addRow(self.multiView, self.singleView)
    self.viewButtonGroup = qt.QButtonGroup()
    self.viewButtonGroup.addButton(self.multiView, 1)
    self.viewButtonGroup.addButton(self.singleView, 2)

  def setupViewerOrientationSettingsUI(self):
    self.orientationBox = qt.QGroupBox()
    orientationBoxLayout = qt.QFormLayout()
    self.orientationBox.setLayout(orientationBoxLayout)
    self.orientationButtons = {}
    self.orientations = ("Axial", "Sagittal", "Coronal")
    for orientation in self.orientations:
      self.orientationButtons[orientation] = self.createRadioButton(orientation, checked=orientation=="Axial")
      orientationBoxLayout.addWidget(self.orientationButtons[orientation])
    self.currentOrientation = 'Axial'

  def setupFiducialsUI(self):
    self.fiducialsArea = ctk.ctkCollapsibleButton()
    self.fiducialsArea.text = "Fiducials"
    self.fiducialsArea.collapsed = True

    self.fiducialsWidget = TargetCreationWidget()
    self.fiducialsWidget.targetListSelectorVisible = True
    self.segmentationWidgetLayout.addWidget(self.fiducialsWidget)

  def setupCompletionUI(self):
    self.piradsButton = qt.QPushButton("PI-RADS v2 review form")
    self.completionWidgetLayout.addWidget(self.piradsButton)

    self.qaButton = qt.QPushButton("Quality Assurance form")
    self.completionWidgetLayout.addWidget(self.qaButton)

    self.saveButton = qt.QPushButton("Save")
    self.completionWidgetLayout.addWidget(self.saveButton)
    '''
      self.piradsButton = qt.QPushButton("PI-RADS review")
      self.layout.addWidget(self.piradsButton)
      # self.piradsButton.connect('clicked()',self.onPiradsClicked)
      '''

  def setupConnections(self):

    # self.dataDirButton.directorySelected.connect(lambda: setattr(self, "inputDataDir", self.dataDirButton.directory))
    self.selectAllSeriesButton.connect('clicked()', lambda: self.selectAllSeries(True))
    self.deselectAllSeriesButton.connect('clicked()', lambda: self.selectAllSeries(False))
    self.modelsVisibilityButton.connect("toggled(bool)", self.onModelsVisibilityButton)
    self.labelMapVisibilityButton.connect("toggled(bool)", self.onLabelMapVisibilityButton)
    self.labelMapOutlineButton.connect('toggled(bool)', self.setLabelOutline)
    self.piradsButton.connect('clicked()', self.onPIRADSFormClicked)
    self.qaButton.connect('clicked()', self.onQAFormClicked)
    self.saveButton.connect('clicked()', self.onSaveClicked)
    for orientation in self.orientations:
      self.orientationButtons[orientation].connect("clicked()", lambda o=orientation: self.setOrientation(o))
    self.viewButtonGroup.connect('buttonClicked(int)', self.onViewUpdateRequested)

    self.enableJumpToROI.connect('toggled(bool)', self.editorWidget.setJumpToSelectedSegmentEnabled)

    self.multiVolumeExplorer.frameSlider.connect('valueChanged(double)', self.onSliderChanged)

    self.studiesView.selectionModel().connect('currentChanged(QModelIndex, QModelIndex)', self.onStudySelected)
    self.seriesView.connect('clicked(QModelIndex)', self.onSeriesSelected)
    
    self.editorWidget.connect("currentSegmentIDChanged(QString)", self.onStructureClicked)

    self.refSelector.connect('currentIndexChanged(int)', self.onReferenceChanged)
    self.tabWidget.connect('currentChanged(int)',self.onTabWidgetClicked)
    
    # self.selectLocalDatabaseButton.clicked.connect(lambda: self.updateStudyTable())
    # self.selectRemoteDatabaseButton.clicked.connect(lambda: self.updateSelectorAvailability())
    
    # if serverURL text is changed
    # self.serverUrlLineEdit.textChanged.connect(lambda: self.onDICOMStoreChanged())
    
    
    # self.selectLocalDatabaseButton.clicked.connect(lambda: self.selectDatabaseOKButton.setEnabled(True))
    self.selectLocalDatabaseButton.clicked.connect(lambda: self.checkWhichDatabaseSelected())
    
    
    # self.selectRemoteDatabaseButton.clicked.connect(lambda: self.updateSelectorAvailability())
    self.selectRemoteDatabaseButton.clicked.connect(lambda : [self.setTabsEnabled([1], False),
                                                              self.setupGoogleCloudPlatform(),
                                                              self.selectDatabaseOKButton.setEnabled(True), 
                                                              self.updateSelectorAvailability(set=True), 
                                                              self.selectOtherRemoteDatabaseOKButton.setEnabled(False), 
                                                              ])
    
    self.selectOtherRemoteDatabaseButton.clicked.connect(lambda : [self.setTabsEnabled([1], False),
                                                                   self.OtherserverUrlLineEdit.setReadOnly(False), 
                                                                   self.selectOtherRemoteDatabaseOKButton.setEnabled(True),
                                                                   self.updateSelectorAvailability(set=False), 
                                                                   self.selectDatabaseOKButton.setEnabled(False)])
    
    self.selectDatabaseOKButton.clicked.connect(lambda: self.checkWhichDatabaseSelected())
    
    self.selectOtherRemoteDatabaseOKButton.clicked.connect(lambda: self.checkWhichDatabaseSelected())
    
    self.serverUrlLineEdit.textChanged.connect(lambda: self.onURLEdited())
    
    self.OtherserverUrlLineEdit.textChanged.connect(lambda: self.onOtherURLEdited()) 



  def enter(self):
    userName = self.getSetting('UserName')
    self.piradsFormURL = self.getSetting('piradsFormURL')
    self.qaFormURL = self.getSetting('qaFormURL')

    if userName is None or userName == '':
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

    if self.piradsFormURL is None or self.piradsFormURL == '':
      # prompt the user for the review form
      # Note: it is expected that the module uses the form of the structure as
      # in http://goo.gl/nT1z4L. The known structure of the form is used to
      # pre-populate the fields corresponding to readerName, studyName and
      # lesionID.
      self.URLPrompt = qt.QDialog()
      self.URLPromptLayout = qt.QVBoxLayout()
      self.URLPrompt.setLayout(self.URLPromptLayout)
      self.URLLabel = qt.QLabel('Enter PI-RADS review form URL:', self.URLPrompt)
      # replace this if you are using a different form
      self.URLText = qt.QLineEdit(self.PIRADS_VIEWFORM_URL)
      self.URLButton = qt.QPushButton('OK', self.URLPrompt)
      self.URLButton.connect('clicked()', self.onPIRADSURLEntered)
      self.URLPromptLayout.addWidget(self.URLLabel)
      self.URLPromptLayout.addWidget(self.URLText)
      self.URLPromptLayout.addWidget(self.URLButton)
      self.URLPrompt.exec_()

      if self.qaFormURL is None or self.qaFormURL == '':
        # prompt the user for the review form
        # Note: it is expected that the module uses the form of the structure as
        # in http://goo.gl/nT1z4L. The known structure of the form is used to
        # pre-populate the fields corresponding to readerName, studyName and
        # lesionID.
        self.URLPrompt = qt.QDialog()
        self.URLPromptLayout = qt.QVBoxLayout()
        self.URLPrompt.setLayout(self.URLPromptLayout)
        self.URLLabel = qt.QLabel('Enter QA review form URL:', self.URLPrompt)
        # replace this if you are using a different form
        self.URLText = qt.QLineEdit(self.QA_VIEWFORM_URL)
        self.URLButton = qt.QPushButton('OK', self.URLPrompt)
        self.URLButton.connect('clicked()', self.onQAURLEntered)
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
      logging.debug('Setting inputlocation in settings to '+inputLocation)
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

  def checkAndSetLUT(self):
    # Default to module color table
    self.terminologyFile = os.path.join(self.resourcesPath, "SegmentationCategoryTypeModifier-mpReview.json")
    # print ('self.terminologyFile: ' + str(self.terminologyFile))

    self.customLUTInfoIcon.show()
    self.customLUTInfoIcon.toolTip = 'Using Default Terminology'

    # # Check for custom LUT
    # terminologyFileLoc = os.path.join(self.inputDataDir, 'SETTINGS', self.inputDataDir.split(os.sep)[-1] + '-terminology.json')
    # logging.debug('Checking for lookup table at : ' + terminologyFileLoc)
    # if os.path.isfile(terminologyFileLoc):
    #   # use custom color table
    #   self.terminologyFile = terminologyFileLoc
    #   self.customLUTInfoIcon.toolTip = 'Project-Specific terminology Found'

    tlogic = slicer.modules.terminologies.logic()
    self.terminologyName = tlogic.LoadTerminologyFromFile(self.terminologyFile)
    # print ('self.terminologyName: ' + str(self.terminologyName))

    # Set the first entry in this terminology as the default so that when the user
    # opens the terminoogy selector, the correct list is shown.
    terminologyEntry = slicer.vtkSlicerTerminologyEntry()
    terminologyEntry.SetTerminologyContextName(self.terminologyName)
    tlogic.GetNthCategoryInTerminology(self.terminologyName, 0, terminologyEntry.GetCategoryObject())
    tlogic.GetNthTypeInTerminologyCategory(self.terminologyName, terminologyEntry.GetCategoryObject(), 0, terminologyEntry.GetTypeObject())
    defaultTerminologyEntry = tlogic.SerializeTerminologyEntry(terminologyEntry)
    self.editorWidget.defaultTerminologyEntry = defaultTerminologyEntry
    
    # self.editorWidget.setDefaultTerminologyEntrySettingsKey(self.editorWidget.defaultTerminologyEntry)

    self.structureNames = []
    numberOfTerminologyTypes = tlogic.GetNumberOfTypesInTerminologyCategory(self.terminologyName, terminologyEntry.GetCategoryObject())
    for terminologyTypeIndex in range(numberOfTerminologyTypes):
      tlogic.GetNthTypeInTerminologyCategory(self.terminologyName, terminologyEntry.GetCategoryObject(), terminologyTypeIndex, terminologyEntry.GetTypeObject())
      self.structureNames.append(terminologyEntry.GetTypeObject().GetCodeMeaning())

    # print(self.structureNames)

    # import json
    # with open(self.terminologyFile) as f:
    #   termData = json.load(f)
    # termCategory = termData["SegmentationCodes"]["Category"][0]
    # termType = termCategory["Type"][0]
    # # defaultTerminologyEntry should look something like this:
    # #   "Segmentation category and type - mpReview~SCT^85756007^Tissue~mpReview^1^WholeGland~^^~Anatomic codes - DICOM master list~^^~^^"
    # defaultTerminologyEntry = (termData["SegmentationCategoryTypeContextName"]
    #   + "~" + termCategory["CodingSchemeDesignator"] + "^" + termCategory["CodeValue"] "^" + termCategory["CodeMeaning"]
    #   + "~" + termType["CodingSchemeDesignator"] + "^" + termType["CodeValue"] "^" + termType["CodeMeaning"]
    #   + "~^^"
    #   + "~Anatomic codes - DICOM master list~^^~^^")

    # There should be a way to set default terminology entry in the widget instead of in the global application settings
    #qt.QSettings().setValue("Segmentations/DefaultTerminologyEntry", defaultTerminologyEntry)

  def onNameEntered(self):
    name = self.nameText.text
    if len(name)>0:
      self.setSetting('UserName', name)
      self.namePrompt.close()
      self.parameters['UserName'] = name

  def onQAURLEntered(self):
    url = self.URLText.text
    if len(url)>0:
      self.setSetting('qaFormURL',url)
      self.URLPrompt.close()
      self.qaFormURL = url

  def onPIRADSURLEntered(self):
    url = self.URLText.text
    if len(url)>0:
      self.setSetting('piradsFormURL',url)
      self.URLPrompt.close()
      self.piradsFormURL = url

  # def onResultsDirEntered(self):
  #   path = self.dirButton.directory
  #   if len(path)>0:
  #     self.setSetting('ResultsLocation',path)
  #     self.dirPrompt.close()
  #     self.parameters['ResultsLocation'] = path

  def onViewUpdateRequested(self, id):
    # Skip if not in a ref image yet
    if self.refSeriesNumber == '-1':
      return

    # Be sure the viewers are linked, they should be but who knows
    self.linkAllSliceWidgets(1)

    layoutNode = slicer.util.getNode('*LayoutNode*')
    if id == 1:
       # If view all
      layoutNode.SetViewArrangement(layoutNode.SlicerLayoutUserView)
    if id == 2:
      # If view ref only
      layoutNode.SetViewArrangement(layoutNode.SlicerLayoutOneUpRedSliceView)

  def onSeriesSelected(self, modelIndex):
    logging.debug('Row selected: '+self.seriesModel.item(modelIndex.row(),0).text())
    selectionModel = self.seriesView.selectionModel()
    logging.debug('Selection model says row is selected: '+str(selectionModel.isRowSelected(modelIndex.row(),
                                                                                            qt.QModelIndex())))
    logging.debug('Row number: '+str(modelIndex.row()))
    self.updateSegmentationTabAvailability()

  def updateSegmentationTabAvailability(self):
    # self.setTabsEnabled([1], any(sItem.checkState() == 2 for sItem in self.seriesItems))
    self.setTabsEnabled([2], any(sItem.checkState() == 2 for sItem in self.seriesItems))


  # def onPIRADSFormClicked(self):
  #   self.webView = qt.QWebView()
  #   self.webView.settings().setAttribute(qt.QWebSettings.DeveloperExtrasEnabled, True)
  #   self.webView.connect('loadFinished(bool)', self.webViewFormLoadedCallback)
  #   self.webView.show()
  #   preFilledURL = self.piradsFormURL
  #   preFilledURL += '?entry.1455103354='+self.getSetting('UserName')
  #   preFilledURL += '&entry.347120626='+self.selectedStudyName
  #   preFilledURL += '&entry.1734306468='+str(self.editorWidget.toolsColor.colorSpin.value)
  #   u = qt.QUrl(preFilledURL)
  #   self.webView.setUrl(u)
  #
  # # https://docs.google.com/forms/d/18Ni2rcooi60fev5mWshJA0yaCzHYvmXPhcG2-jMF-uw/viewform?entry.1920755914=READER&entry.204001910=STUDY
  # def onQAFormClicked(self):
  #   self.webView = qt.QWebView()
  #   self.webView.settings().setAttribute(qt.QWebSettings.DeveloperExtrasEnabled, True)
  #   self.webView.connect('loadFinished(bool)', self.webViewFormLoadedCallback)
  #   self.webView.show()
  #   preFilledURL = self.qaFormURL
  #   preFilledURL += '?entry.1920755914='+self.getSetting('UserName')
  #   preFilledURL += '&entry.204001910='+self.selectedStudyName
  #   print('Pre-filled URL:'+preFilledURL)
  #   u = qt.QUrl(preFilledURL)
  #   self.webView.setUrl(u)
  
  def onPIRADSFormClicked(self):
    self.webView = slicer.qSlicerWebWidget()
    # self.webView.settings().setAttribute(qt.QWebSettings.DeveloperExtrasEnabled, True)
    # self.webView.connect('loadFinished(bool)', self.webViewFormLoadedCallback)
    self.webView.show()
    preFilledURL = self.piradsFormURL
    preFilledURL += '?entry.1455103354='+self.getSetting('UserName')
    preFilledURL += '&entry.347120626='+self.selectedStudyName
    u = qt.QUrl(preFilledURL)
    # print ('u: ' + str(u))
    # self.webView.setUrl(u)
    self.webView.setUrl(preFilledURL)
    slicer.app.openUrl(u)

  # https://docs.google.com/forms/d/18Ni2rcooi60fev5mWshJA0yaCzHYvmXPhcG2-jMF-uw/viewform?entry.1920755914=READER&entry.204001910=STUDY
  def onQAFormClicked(self):
    self.webView = slicer.qSlicerWebWidget()
    # self.webView.settings().setAttribute(qt.QWebSettings.DeveloperExtrasEnabled, True)
    # self.webView.connect('loadFinished(bool)', self.webViewFormLoadedCallback)
    self.webView.show()
    preFilledURL = self.qaFormURL
    preFilledURL += '?entry.1920755914='+self.getSetting('UserName')
    preFilledURL += '&entry.204001910='+self.selectedStudyName
    print('Pre-filled URL:'+preFilledURL)
    u = qt.QUrl(preFilledURL)
    # print ('u: ' + str(u))
    # self.webView.setUrl(u)
    self.webView.setUrl(preFilledURL)
    slicer.app.openUrl(u)


  def webViewFormLoadedCallback(self,ok):
    if not ok:
      logging.debug('page did not load')
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

    timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    username = self.getSetting('UserName')
    
    if (self.selectLocalDatabaseButton.isChecked()):
      savedMessage = self.saveSegmentations(timestamp, username, database_type="local") 
    elif (self.selectRemoteDatabaseButton.isChecked() or self.selectOtherRemoteDatabaseButton.isChecked()):
      savedMessage = self.saveSegmentations(timestamp, username, database_type="remote")
    
    '''
    volumeNodes = slicer.util.getNodes('vtkMRMLScalarVolumeNode*')
    logging.debug('All volume nodes: '+str(volumeNodes))
    for key in volumeNodes.keys():
      vNode = volumeNodes[key]
      if vNode.GetAttribute('LabelMap') == '1':
        continue
      seriesNumber = string.split(key,':')[0]
      logging.debug('W/L for series '+seriesNumber+' is '+str(vNode.GetDisplayNode().GetWindow()))
      f = open(wlSettingsDir+'/'+seriesNumber+'-wl.txt','w')
      f.write(str(vNode.GetDisplayNode().GetWindow())+' '+str(vNode.GetDisplayNode().GetLevel()))
      f.close()
    '''

    savedMessage += "\n " + self.saveTargets(username, timestamp)
    slicer.util.infoDisplay(savedMessage, windowTitle="mpReview")
    
  def saveSegmentations(self, timestamp, username, database_type):
    
    labelNodes = slicer.util.getNodes('*-label*')
    logging.debug('All label nodes found: ' + str(labelNodes))
    savedMessage = 'Segmentations for the following series were saved:\n\n'
    
    import DICOMSegmentationPlugin
    # DICOMSegmentationPlugin = slicer.modules.dicomPlugins['DICOMSegmentationPlugin']()
    exporter = DICOMSegmentationPlugin.DICOMSegmentationPluginClass()
    
    success = 0 
    
    db = slicer.dicomDatabase
    
    for label in labelNodes.values():
    
        labelSeries = label.GetName().split(':')[0]
        labelName = label.GetName().split(':')[1]
        labelName_ref = label.GetName()[:label.GetName().rfind("-")]
      
        segmentationsDir = os.path.join(db.databaseDirectory, self.selectedStudyName, labelSeries) 
        self.logic.createDirectory(segmentationsDir) 
        
        volume_nodes = slicer.util.getNodesByClass('vtkMRMLScalarVolumeNode')
        volume_names = [f.GetName() for f in volume_nodes]
        matching_index = volume_names.index(labelName_ref)
        referenceVolumeNode = volume_nodes[matching_index]
        
        # temp2 = shNode.GetItemDataNode(shNode.GetItemByName('6:T2 Weighted Axial-label'))
        shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
        
        # set these for now. 
        # study list could be from different patients. 
        patientItemID = shNode.CreateSubjectItem(shNode.GetSceneItemID(), self.selectedStudyName)
        studyItemID = shNode.CreateStudyItem(patientItemID, self.selectedStudyName)
        volumeShItemID = shNode.GetItemByDataNode(referenceVolumeNode) # set volume node 
        shNode.SetItemParent(volumeShItemID, studyItemID)
        segmentationShItem = shNode.GetItemByDataNode(label) # segmentation
        shNode.SetItemParent(segmentationShItem, studyItemID)
        
        
        if (database_type=="local"):
        
          # Export to DICOM
          exportables = exporter.examineForExport(segmentationShItem)
          for exp in exportables:
            exp.directory = segmentationsDir
            exp.setTag('ContentCreatorName', username)
          # exporter.export(exportables)
          
          # uniqueID = username + '-' + "SEG" + '-' + timestamp 
          # labelFileName = os.path.join(segmentationsDir, uniqueID + ".dcm")
          
          labelFileName = os.path.join(segmentationsDir, 'subject_hierarchy_export.SEG'+exporter.currentDateTime+".dcm")
          print ('labelFileName: ' + str(labelFileName))
     
          # exporter.export(exportables, labelFileName)
          exporter.export(exportables)
          
        elif (database_type=="remote"):
        
          # Create temporary directory for saving the DICOM SEG file  
          downloadDirectory = os.path.join(slicer.dicomDatabase.databaseDirectory,'tmp')
          if not os.path.isdir(downloadDirectory):
            os.mkdir(downloadDirectory)
            
          # Export to DICOM
          exportables = exporter.examineForExport(segmentationShItem)
          for exp in exportables:
            exp.directory = downloadDirectory
            exp.setTag('ContentCreatorName', username)
          
          labelFileName = os.path.join(downloadDirectory, 'subject_hierarchy_export.SEG'+exporter.currentDateTime+".dcm")
          print ('labelFileName: ' + str(labelFileName))
     
          exporter.export(exportables)
          
          # Upload to remote server 
          # self.copySegmentationsToRemote(labelFileName) # this one uses buckets and DICOM datastores 
          print('uploading seg dcm file to the remote server')
          self.copySegmentationsToRemoteDicomweb(labelFileName) # this one uses dicomweb client 
          
          # Now delete the files from the temporary directory 
          for f in os.listdir(downloadDirectory):
            os.remove(os.path.join(downloadDirectory, f))
          # Delete the temporary directory 
          os.rmdir(downloadDirectory)
      
          # also remove from the dicom database - it was added automatically?
          
        success = 1 
      
        if success:
            savedMessage = savedMessage + label.GetName() + '\n'
            logging.debug(label.GetName() + ' has been saved to ' + labelFileName)

    return savedMessage
  
  def copySegmentationsToRemoteDicomweb(self, labelFileName):
    """Uses the dicomweb client to store DICOM SEG instance in the remote server"""
    
    # print ('in copySegmentationsToRemoteDicomweb')
    dataset = pydicom.dcmread(labelFileName)
    # print('dataset: ' + str(dataset))
    
    # self.DICOMwebClient.store_instances(datasets=[dataset], study=self.selectedStudyNumber)
    self.DICOMwebClient.store_instances(datasets=[dataset])

    
    return 

    
  
  def copySegmentationsToRemote(self, labelFileName):
    """Uses buckets and the DICOM datastore to store DICOM SEG instance in the remote server"""
    
    # create a temporary bucket
    import random
    import string  
    slicer.util.pip_install('google-cloud-storage') # fix this later wtih proper testing etc.  
    from google.cloud import storage
    
    # create temporary bucket
    bucket_name = ''.join(random.choices(string.ascii_lowercase, k=15))
    self.create_bucket(bucket_name, project_id=self.project, location_id=self.location)
    # gsutil mb -p PROJECT_ID -c STORAGE_CLASS -l BUCKET_LOCATION -b on gs://BUCKET_NAME
 
    # upload file to bucket 
    self.upload_file_to_bucket(labelFileName, bucket_name, project_id=self.project)
    
    # create dicomStore for only SEG if it doesn't already exist
    # self.dicomStore_seg = self.dicomStore + '_seg' 
    # dicomStores_list = self.gcp.dicomStores(project=self.project, dataset=self.dataset)
    # if not (self.dicomStore_seg in dicomStores_list):
    #   self.gcp.create_dicomStore(project=self.project, 
    #                              location=self.location, 
    #                              dataset=self.dataset,
    #                              dicomStore=self.dicomStore_seg)

    # copy the SEG file from bucket to the dicom data store selected 
    self.gcp.copy_from_bucket_to_dicomStore(project=self.project, 
                                            location=self.location, 
                                            dataset=self.dataset, 
                                            dicomStore=self.dicomStore, 
                                            bucket_name=bucket_name)
    # self.gcp.copy_from_bucket_to_dicomStore(project=self.project, 
    #                                     location=self.location, 
    #                                     dataset=self.dataset, 
    #                                     dicomStore=self.dicomStore_seg, 
    #                                     bucket_name=bucket_name)

    # remove files from bucket 
    self.remove_files_from_bucket(bucket_name, project_id=self.project)
    
    # delete bucket  
    self.delete_bucket(bucket_name, project_id=self.project)
    
    return 

  
  def create_bucket(self, bucket_name, project_id, location_id):

    from google.cloud import storage 
    
    storage_client = storage.Client(project=project_id)
    bucket = storage_client.bucket(bucket_name)
    bucket.location = location_id
    bucket.storage_class = "STANDARD"
    new_bucket = storage_client.create_bucket(bucket, project=project_id)

    return new_bucket

  def upload_file_to_bucket(self, source_file_name, bucket_name, project_id):
    
    # gsutil -m cp -r labelFileName gs://mpreview_bucket
    
    from google.cloud import storage 
    
    destination_blob_name = os.path.basename(source_file_name)
    storage_client = storage.Client(project=project_id)
    bucket = storage_client.bucket(bucket_name)
    blob = bucket.blob(destination_blob_name)
    blob.upload_from_filename(source_file_name)
    
    return 
  
  def remove_files_from_bucket(self, bucket_name, project_id):
  
    # Get the blob names 
    blob_names = self.list_blobs(bucket_name, project_id)
    # Delete the blobs 
    self.delete_blob_list(bucket_name, blob_names, project_id)
  
    return 
  
  # Adapted from
  # https://cloud.google.com/storage/docs/samples/storage-list-files#storage_list_files-python
  def list_blobs(self, bucket_name, project_id):
    """Lists all the blobs in the bucket."""
    
    from google.cloud import storage
  
    storage_client = storage.Client(project=project_id)
  
    # Note: Client.list_blobs requires at least package version 1.17.0.
    blobs = storage_client.list_blobs(bucket_name)
  
    blob_names = [f.name for f in blobs]

    return blob_names

  # Adapted from 
  # https://cloud.google.com/storage/docs/deleting-objects#storage-delete-object-python 
  def delete_blob_list(self, bucket_name, blob_names, project_id):
    """Deletes a list of blobs from the bucket."""
    
    from google.cloud import storage
    
    storage_client = storage.Client(project=project_id)
  
    bucket = storage_client.bucket(bucket_name)
  
    num_blobs = len(blob_names)
    for n in range(0,num_blobs):
      blob_name = blob_names[n]
      blob = bucket.blob(blob_name)
      blob.delete()
  
      return 

  
  def delete_bucket(self, bucket_name, project_id):
    """Deletes a bucket. The bucket must be empty."""
    # bucket_name = "your-bucket-name"
    
    from google.cloud import storage

    storage_client = storage.Client(project=project_id)

    bucket = storage_client.get_bucket(bucket_name)
    bucket.delete()
    
    return 
  

  def saveTargets(self, username, timestamp):
    savedMessage = ""
    fiducialsNode = self.fiducialsWidget.currentNode
    if fiducialsNode:
      targetsDir = os.path.join(self.inputDataDir, self.selectedStudyName, 'Targets')
      self.logic.createDirectory(targetsDir)
      targetFileName = username+'-'+timestamp+'.fcsv'
      path = os.path.join(targetsDir, targetFileName)
      if slicer.util.saveNode(fiducialsNode, path):
        savedMessage = 'Fiducials were saved'
    return savedMessage

  def setLabelOutline(self, toggled):
    # Update button text
    if toggled:
      self.labelMapOutlineButton.setText('Filled')
    else:
      self.labelMapOutlineButton.setText('Outline')

    # Set outline on widgets
    self.editorWidget.segmentationNode().GetDisplayNode().SetVisibility2DFill(not toggled)

  def onModelsVisibilityButton(self,toggled):
    if self.refSeriesNumber != '-1':
      ref = self.refSeriesNumber
      refLongName = self.seriesMap[ref]['LongName']

      outHierarchy = None
      numNodes = slicer.mrmlScene.GetNumberOfNodesByClass( "vtkMRMLModelHierarchyNode" )
      for n in range(numNodes):
        node = slicer.mrmlScene.GetNthNodeByClass( n, "vtkMRMLModelHierarchyNode" )
        if node.GetName() == 'mpReview-'+refLongName:
          outHierarchy = node
          break

      if outHierarchy:
        collection = vtk.vtkCollection()
        outHierarchy.GetChildrenModelNodes(collection)
        n = collection.GetNumberOfItems()
        if n != 0:
          for i in range(n):
            modelNode = collection.GetItemAsObject(i)
            displayNode = modelNode.GetDisplayNode()
            displayNode.SetSliceIntersectionVisibility(0 if toggled else 1)
            self.modelsVisibilityButton.setText('Show' if toggled else 'Hide')
          self.updateViewRenderer()

  def onLabelMapVisibilityButton(self, toggled):
    self.labelMapVisibilityButton.setText('Show' if toggled else 'Hide')
    sliceLogics = self.layoutManager.mrmlSliceLogics()
    for n in range(sliceLogics.GetNumberOfItems()):
      sliceLogic = sliceLogics.GetItemAsObject(n)
      widget = self.layoutManager.sliceWidget(sliceLogic.GetName())
      redCompositeNode = widget.mrmlSliceCompositeNode()
      redCompositeNode.SetLabelOpacity(0.0 if toggled else 1.0)
      
  

  def setTabsEnabled(self, indexes, enabled):
    for index in indexes:
      self.tabWidget.childAt(1, 1).setTabEnabled(index, enabled)
      
  def onStep0Selected(self):
    if self.checkStep2or3Leave() is True:
      return False
    else:
      return True 
    # return True 

  def checkStep2or3Leave(self):
    # if self.currentTabIndex in [1,2]:
    # if self.currentTabIndex in [1,2,3]: # or [2,3]?
    if self.currentTabIndex in [2,3]:
      continueCurrentStep = self.showExitStep3Or4Warning()
      if continueCurrentStep:
        self.tabWidget.setCurrentIndex(self.currentTabIndex)
        return True
    return False

  def onStep1Selected(self):
    if self.checkStep2or3Leave() is True:
      return False
    self.setCrosshairEnabled(False)

    self.editorWidget.setActiveEffect(None)
    # if len(self.studiesView.selectedIndexes()) > 0:
    #   self.onStudySelected(self.studiesView.selectedIndexes()[0])
      
    # self.updateSegmentationTabAvailability()
    return True
  
  def checkWhichDatabaseSelected(self):
    # OK button was clicked. 
    # Check if local or remote Qradio button was clicked 
    
    # If local was clicked, updateStudyTable 
    if self.selectLocalDatabaseButton.isChecked():
      # disable the GCP project etc selectors and server url and ok button 
      self.updateSelectorAvailability(set=False)
      self.selectDatabaseOKButton.setEnabled(False)
      self.serverUrlLineEdit.setReadOnly(True)
      # disable the other server url and ok button 
      self.selectOtherRemoteDatabaseOKButton.setEnabled(False)
      self.OtherserverUrlLineEdit.setReadOnly(True)
      # update study table 
      self.updateStudyTable() 
      
    elif self.selectRemoteDatabaseButton.isChecked():
      # disable the other server url and ok button 
      # self.selectOtherRemoteDatabaseOKButton.setEnabled(False)
      # self.OtherserverUrlLineEdit.setReadOnly(True)
      # update study table 
      self.updateStudyTableRemote()
      
    elif self.selectOtherRemoteDatabaseButton.isChecked():
      # disable the GCP project etc selectors and server url and ok button 
      # self.updateSelectorAvailability(set=False)
      # self.selectDatabaseOKButton.setEnabled(False)
      # self.serverUrlLineEdit.setReadOnly(True)
      # set serverurl to be edited 
      # self.OtherserverUrlLineEdit.setReadOnly(False)
      # update study table 
      self.updateOtherStudyTableRemote()
      
  
      
      ### old ###
      # self.onDICOMStoreChanged()
      
      ### old ### 
      # first check if the serverURL is valid
      # if self.isValidserverURL:  
      # if valid, updateStudyTableRemote()
      
      # if not valid, show error message 
      # self.updateStudyTableRemote()
      

  def updateStudyTable(self):
    # need to have Study Selection tab enabled 
    self.updateStudiesAndSeriesTabAvailability()
    
    self.studiesModel.clear()
    # self.fillStudyTable()
    self.fillStudyTableDICOMDatabase()
    # if self.logic.wasmpReviewPreprocessed(self.inputDataDir):
    #   self.fillStudyTable()
    # else:
    #   self.notifyUserAboutMissingEligibleData()
    
  def updateStudyTableRemote(self):
    # authorize 
    self.dicomwebAuthorize()
    # fill the studies 
    self.studiesMap = {} 
    ## self.getStudyNamesRemoteDatabase()    # 5-26-22  
    self.fillStudyTableRemoteDatabase()

    # update the availability of the next tab 
    self.updateStudiesAndSeriesTabAvailability()
    
  def updateOtherStudyTableRemote(self):
    # authorize 
    # self.dicomwebAuthorize()
    self.dicomwebOtherAuthorize()
    # fill the studies 
    self.studiesMap = {} 
    ## self.getStudyNamesRemoteDatabase()    # 5-26-22  
    self.fillStudyTableRemoteDatabase()

    # update the availability of the next tab 
    self.updateStudiesAndSeriesTabAvailability()
    
    
  def updateSelectorAvailability(self, set=True):
  
    # ungray out the selection 
    if (set):
          
      self.projectSelectorCombobox.setEnabled(True)
      self.projectSelectorCombobox.setEditable(True)
      self.datasetSelectorCombobox.setEnabled(True)
      self.dicomStoreSelectorCombobox.setEnabled(True)
      self.serverUrlLineEdit.setReadOnly(False)
      
    else:
      
      self.projectSelectorCombobox.setEnabled(False)
      self.projectSelectorCombobox.setEditable(False)
      self.datasetSelectorCombobox.setEnabled(False)
      self.dicomStoreSelectorCombobox.setEnabled(False)
      self.serverUrlLineEdit.setReadOnly(True)
      
    
  def getTagValue(self, study, tag_name):
    """This function takes as input a single study metadata from dicomweb and 
      a tag_name, and returns the numeric string for that name"""
      
    if tag_name is "PatientID":
      tag_numeric = '00100020'
    elif tag_name is "StudyDate":
      tag_numeric = '00080020'
    elif tag_name is "StudyInstanceUID":
      tag_numeric = '0020000D'
    elif tag_name is "SeriesInstanceUID": 
      tag_numeric = '0020000E'
    elif tag_name is "SeriesNumber":
      tag_numeric = '00200011'
    elif tag_name is "SeriesDescription":
      tag_numeric = '0008103E'
    elif tag_name is "SOPInstanceUID": 
      tag_numeric = '00080018'
    
    try:
      study_value = study[tag_numeric]['Value']
      if type(study_value) == list:
        study_value = study_value[0]
    except KeyError:
      study_value = ""
    
    return study_value 
  
  def getPatientIDsRemoteDatabase(self, studies):
    
    patientList = [] 
    num_studies = len(studies)
    for study in studies: 
      # patientID = study['00100010']['Value'][0]['Alphabetic']
      patientID = self.getTagValue(study, 'PatientID')
      patientList.append(patientID)
    patientList = list(set(patientList))
      
    return patientList 
  
  def getStudyNamesRemoteDatabase(self):
    
    print ('********** Getting the studies to update the study names *******')
    
    # Get the studies 
    offset = 0 
    studies = [] 
    while True:
      subset = self.DICOMwebClient.search_for_studies(offset=offset)
      if len(subset) == 0:
        break
      if subset[0] in studies:
        # got the same study twice, so probably this server does not respect offset,
        # therefore we cannot do paging
        break
      studies.extend(subset)
      offset += len(subset) 
    # print ('search_for_studies in remote database')
    
    # Iterate over each patient ID, get the appropriate list of studies 
    studiesMap = {} 
    ShortNames = [] 
    for study in studies: 
      # patient = study['00100010']['Value'][0]['Alphabetic']
      patient = self.getTagValue(study, 'PatientID')
      
      # studyDate = study['00080020']['Value'][0]
      studyDate = self.getTagValue(study, 'StudyDate')
      
      # ShortName = patient_studyDate
      ShortName = patient + '_' + studyDate
      # LongName = SeriesDescription
      # seriesDescription = study['00080030']['Value'][0] # this is the study description, need series Description
      # LongName = seriesDescription 
      # set the values 
      # studyUID = study['0020000D']['Value'][0]
      studyUID = self.getTagValue(study, 'StudyInstanceUID')
      
      studiesMap[studyUID] = {'ShortName': ShortName}
      studiesMap[studyUID]['LongName'] = '' # can remove LongName later
      studiesMap[studyUID]['StudyInstanceUID'] = studyUID
      ShortNames.append(ShortName)
      
      
    # Order the study names according to the ShortName 
    # ShortNames = [f for f in ]
    
    # # Get a list of patient ids from the above studies 
    # patientList = self.getPatientIDsRemoteDatabase(studies)
    #
    # # Iterate over each patient ID, get the appropriate list of studies 
    # studiesMap = {} 
    # for patient in patientList: 
    #   # studiesPerPatient = client.search_for_studies(search_filters={'PatientID': patient})
    #   studiesPerPatient = self.DICOMwebClient.search_for_studies(search_filters={'PatientID': patient})
    #   for study in studiesPerPatient: 
    #     studyDate = study['00080020']['Value'][0]
    #     # ShortName = patient_studyDate
    #     ShortName = patient + '_' + studyDate
    #     # LongName = SeriesDescription
    #     # seriesDescription = study['00080030']['Value'][0] # this is the study description, need series Description
    #     # LongName = seriesDescription 
    #     # set the values 
    #     studyUID = study['0020000D']['Value'][0]
    #     studiesMap[studyUID] = {'ShortName': ShortName}
    #     studiesMap[studyUID]['LongName'] = '' # can remove LongName later
    #     studiesMap[studyUID]['StudyInstanceUID'] = studyUID
        
    # print ('studiesMap: ' + str(studiesMap))  
    self.studiesMap = studiesMap 
        
    return studiesMap 
        

  def notifyUserAboutMissingEligibleData(self):
    outputDirectory = os.path.abspath(self.inputDataDir) + "_" + datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    mbox = qt.QMessageBox()
    mbox.icon = qt.QMessageBox.Question
    mbox.text = "The selected directory is not eligible for using with mpReview.\n\n" \
                "Do you want to parse the directory and preprocess found DICOM data?\n\n" \
                "Output directory (browse to change): \n\n%s\n\n" \
                "NOTE: The original DICOM data will not be modified." % outputDirectory
    okButton = mbox.addButton(qt.QMessageBox.Ok)
    browseButton = self.createButton("Browse", icon=ctk.ctkDirectoryButton().icon)
    mbox.addButton(browseButton, qt.QMessageBox.ActionRole)
    mbox.addButton(qt.QMessageBox.Cancel)
    mbox.exec_()
    selectedButton = mbox.clickedButton()
    if selectedButton in [browseButton, okButton]:
      if selectedButton is browseButton:
        selectedDir = qt.QFileDialog.getExistingDirectory(None, self.inputDataDir)
        if selectedDir and selectedDir != self.inputDataDir:
          outputDirectory = selectedDir
        else:
          if selectedDir == self.inputDataDir:
            slicer.util.warningDisplay("The output directory cannot be the input data directory Please choose another "
                                       "directory.", windowTitle="mpReview")
          return self.updateStudyTable()
      success = self.invokePreProcessing(outputDirectory)
      if success:
        self.dataDirButton.directory = outputDirectory
      else:
        slicer.util.infoDisplay("No DICOM data could be processed. Please select another directory.",
                                windowTitle="mpReview")

    
  def fillSeriesTable(self):
    
    # for s in seriesList: 
    for s in sorted([int(x) for x in self.seriesMap.keys()]):
      # seriesText = s 
      seriesText = str(s) + ':' + self.seriesMap[str(s)]['LongName']
      sItem = qt.QStandardItem(seriesText) 
      self.seriesItems.append(sItem)   
      self.seriesModel.appendRow(sItem)
      sItem.setCheckable(1)
      if self.logic.isSeriesOfInterest(seriesText):
        sItem.setCheckState(2)
    
  def updateSeriesTable(self):
    
    self.seriesItems = []  
    self.seriesModel.clear()
    db = slicer.dicomDatabase
    seriesList = db.seriesForStudy(self.selectedStudyNumber)
    
    # Form the self.seriesMap before setting the items in table 
    seriesMap = {} 
    for series in seriesList: 
      fileList = db.filesForSeries(series)
      seriesDescription = db.fileValue(fileList[0], "0008,103e")
      # if label in the seriesDescription, skip this 
      if "label" not in seriesDescription: 
        seriesNumber = db.fileValue(fileList[0], "0020,0011")
        seriesMap[seriesNumber] = {'ShortName': str(seriesNumber)+":"+seriesDescription, 
                                   'LongName': seriesDescription, 
                                   'seriesInstanceUID': series} 
        # seriesMap[seriesNumber] = {'MetaInfo':None, 'DICOMLocation':dicomFilesDirectory,'LongName':seriesDescription, 
        #                            'patientName':patientName, 'studyInstanceUID':studyInstanceUID, 'seriesInstanceUID':seriesInstanceUID}
        # seriesMap[seriesNumber]['ShortName'] = str(seriesNumber)+":"+seriesDescription
    
    self.seriesMap = seriesMap 
    # print ('self.seriesMap: ' + str(self.seriesMap))
    
    self.fillSeriesTable()
        
    self.updateSegmentationTabAvailability()  
    
  def updateSeriesTableRemote(self):
    
    self.seriesItems = []  
    self.seriesModel.clear()
    
    # Get the studyInstanceUID of the study selected 
    studyInstanceUID = self.selectedStudyNumber
    
    # Get the series 
    print ('******** Getting the series to update the series table remote ******')
    seriesList = self.DICOMwebClient.search_for_series(studyInstanceUID)
    # print ('seriesList: ' + str(seriesList))
    # print ('search_for_series in remote database')
    
    self.seriesList = seriesList 

    seriesMap = {} 
    for series in seriesList: 
      # seriesNumber = series['00200011']['Value'][0] # seriesNumber doesn't exist.. 
      # need to get metadata 
      # seriesInstanceUID = series['00081030']['Value'][0]
      # seriesInstanceUID = series['0020000E']['Value'][0]
      seriesInstanceUID = self.getTagValue(series, 'SeriesInstanceUID')
      
      metadata = self.DICOMwebClient.retrieve_series_metadata(study_instance_uid=studyInstanceUID,
                                                              series_instance_uid=seriesInstanceUID
                                                              )
      # print ('metadata[0]: ' + str(metadata[0]))
      # seriesNumber = str(metadata[0]['00200011']['Value'][0])
      seriesNumber = str(self.getTagValue(metadata[0], 'SeriesNumber')) 
      
      # seriesInstanceUID = series['00081030']['Value'][0]
      # seriesDescription = series['0008103E']['Value'][0]
      seriesDescription = self.getTagValue(series, 'SeriesDescription')
      
      ShortName = str(seriesNumber)+":"+seriesDescription
      
      if "label" not in seriesDescription: 
        seriesMap[seriesNumber] = {'ShortName': ShortName, 
                                   'LongName': seriesDescription, 
                                   'seriesInstanceUID': seriesInstanceUID} 
    self.seriesMap = seriesMap 
    # print ('self.seriesMap: ' + str(self.seriesMap))
    # print ('retrieve_series_metadata in remote database')
    
    self.fillSeriesTable()
        
    self.updateSegmentationTabAvailability()  
    

  def fillStudyTable(self):
    self.studyItems = []
    self.seriesModel.clear()
    dirs = self.logic.getStudyNames(self.inputDataDir)
    dirs.sort()
    progress = self.createProgressDialog(maximum=len(dirs))
    for studyIndex, studyName in enumerate(dirs, start=1):
      if os.path.isdir(os.path.join(self.inputDataDir, studyName)) and studyName != 'SETTINGS':
        sItem = qt.QStandardItem(studyName)
        self.studyItems.append(sItem)
        self.studiesModel.appendRow(sItem)
        logging.debug('Appended to model study ' + studyName)
        progress.setValue(studyIndex)
        slicer.app.processEvents()
    # TODO: unload all volume nodes that are already loaded
    progress.close()
    if len(self.studyItems) == 1:
      modelIndex = self.studiesModel.index(0,0)
      self.studiesView.selectionModel().setCurrentIndex(modelIndex, self.studiesView.selectionModel().Select)
      self.studiesView.selectionModel().select(modelIndex, self.studiesView.selectionModel().Select)
      
  def fillStudyTableDICOMDatabase(self):
    
    self.studyItems = [] 
    self.seriesModel.clear() 
    self.studiesMap = self.logic.getStudyNamesDICOMDatabase()
    self.setStudiesView()
    
  def fillStudyTableRemoteDatabase(self):
    
    self.studyItems = [] 
    self.studiesModel.clear()
    self.seriesModel.clear()
    self.studiesMap = self.getStudyNamesRemoteDatabase()
    self.setStudiesView()
    
  def setStudiesView(self):
    
    # for s in sorted([int(x) for x in self.studiesMap.keys()]):
    for s in [x for x in self.studiesMap.keys()]: 
      # studiesText = str(s) + ':' + self.studiesMap[str(s)]['LongName']
      # studiesText = self.studiesMap[str(s)]['LongName']
      studiesText = self.studiesMap[str(s)]['ShortName'] # patientname_studydate 
      sItem = qt.QStandardItem(studiesText)
      self.studyItems.append(sItem)
      self.studiesModel.appendRow(sItem)
      # logging.debug('Appended to model study ' + studyName)
      logging.debug('Appended to model study ' + studiesText)
      # progress.setValue(studyIndex)
      slicer.app.processEvents()
    if len(self.studyItems) == 1:
      modelIndex = self.studiesModel.index(0,0)
      self.studiesView.selectionModel().setCurrentIndex(modelIndex, self.studiesView.selectionModel().Select)
      self.studiesView.selectionModel().select(modelIndex, self.studiesView.selectionModel().Select)
      

  def invokePreProcessing(self, outputDirectory):
    self.mpReviewPreprocessorLogic = mpReviewPreprocessorLogic()
    self.progress = self.createProgressDialog()
    self.progress.canceled.connect(lambda : self.mpReviewPreprocessorLogic.cancelProcess())
    self.logic.createDirectory(outputDirectory)
    success = self.mpReviewPreprocessorLogic.importAndProcessData(self.inputDataDir, outputDir=outputDirectory,
                                                                  copyDICOM=True,
                                                                  progressCallback=self.updateProgressBar)
    self.progress.canceled.disconnect(lambda : self.mpReviewPreprocessorLogic.cancelProcess())
    self.progress.close()
    return success

  def updateProgressBar(self, **kwargs):
    ModuleWidgetMixin.updateProgressBar(self, progress=self.progress, **kwargs)

  def onStudySelected(self, modelIndex):
    self.studiesGroupBox.collapsed = True
    logging.debug('Row selected: '+self.studiesModel.item(modelIndex.row(),0).text())
    selectionModel = self.studiesView.selectionModel()
    logging.debug('Selection model says row is selected: '+str(selectionModel.isRowSelected(modelIndex.row(),
                                                                                            qt.QModelIndex())))
    logging.debug('Row number: '+str(modelIndex.row()))

    self.setTabsEnabled([2], False)

    self.logic.cleanupDir(self.tempDir)

    # if any volumes have been loaded (we returned back from a previous step)
    # then remove all of them from the scene
    allVolumeNodes = slicer.util.getNodes('vtkMRML*VolumeNode*')
    for node in allVolumeNodes.values():
      slicer.mrmlScene.RemoveNode(node)

    self.selectedStudyName = self.studiesModel.item(modelIndex.row(),0).text()
    # print ('self.selectedStudyName: ' + str(self.selectedStudyName))
    self.selectedStudyNumber = list(self.studiesMap.keys())[[f['ShortName'] for f in list(self.studiesMap.values())].index(self.selectedStudyName)]
    # print ('self.selectedStudyNumber: ' + str(self.selectedStudyNumber))
    self.parameters['StudyName'] = self.selectedStudyName

    # self.resourcesDir = os.path.join(self.inputDataDir, self.selectedStudyName, 'RESOURCES')

    # self.progress = self.createProgressDialog(maximum=len(os.listdir(self.resourcesDir)))
    # self.seriesMap, metaFile = self.logic.loadMpReviewProcessedData(self.resourcesDir,
    #                                                                 updateProgressCallback=self.updateProgressBar)
    # self.seriesMap, metaFile = self.logic.loadMpReviewProcessedDataDICOM(self.resourcesDir,
    #                                                                      updateProgressCallback=self.updateProgressBar)
    # self.informationWatchBox.sourceFile = metaFile
    self.informationWatchBox.setInformation("StudyID", self.selectedStudyName)
    #
    # added 
    # self.seriesMap = self.logic. 
    
    if (self.selectLocalDatabaseButton.isChecked()):
      self.updateSeriesTable()
    elif (self.selectRemoteDatabaseButton.isChecked()):
      self.updateSeriesTableRemote()
    elif (self.selectOtherRemoteDatabaseButton.isChecked()):
      self.updateSeriesTableRemote()
      
    
    
    #
    self.selectAllSeriesButton.setEnabled(True)
    self.deselectAllSeriesButton.setEnabled(True)
    #
    # self.progress.delete()
    # self.setTabsEnabled([1], True)
    self.setTabsEnabled([2], True)
    
  def loadVolumeFromLocalDatabase(self, seriesNumber): 
    """ Load a series from the local DICOM database """
    
    db = slicer.dicomDatabase
    
    # Get appropriate files 
    seriesInstanceUID = self.seriesMap[seriesNumber]['seriesInstanceUID']
    fileList = db.filesForSeries(seriesInstanceUID)

    # Now load
    import DICOMScalarVolumePlugin
    scalarVolumeReader = DICOMScalarVolumePlugin.DICOMScalarVolumePluginClass()
    loadable = scalarVolumeReader.examineForImport([fileList])[0]
    volume = scalarVolumeReader.load(loadable)
    
    return volume 
  
  def loadVolumeFromRemoteDatabase(self, selectedStudy, selectedSeries):
    """ Load a series from a remote DICOM server """
          
    indexer = ctk.ctkDICOMIndexer()  
    indexer.backgroundImportEnabled=True    
    
    db = slicer.dicomDatabase   
  
    # A temporary directory for the downloaded DICOM files from the remote database 
    downloadDirectory = os.path.join(slicer.dicomDatabase.databaseDirectory, 'tmp')
    if not os.path.isdir(downloadDirectory):
      # os.mkdir(downloadDirectory)
      os.makedirs(downloadDirectory)
     
    # Get the instances corresponding to the chosen study and series  
    print ('********** Searching for instances for volumes from remote database *********')    
    instances = self.DICOMwebClient.search_for_instances(
                          study_instance_uid=selectedStudy,
                          series_instance_uid=selectedSeries
                          )
    # print ('slicer process events')
    # slicer.app.processEvents()
    # print ('search_for_instances in remote database')
    
    # The instances that are already in the DICOM database, no need to download  
    instancesAlreadyInDatabase = slicer.dicomDatabase.instancesForSeries(selectedSeries)
    
    # Download and write the files that are not currently in the DICOM database 
    print('downloading and writing the files that are currently not in the DICOM database')
    for instanceIndex, instance in enumerate(instances):
      # sopInstanceUid = instance['00080018']['Value'][0]
      sopInstanceUid = self.getTagValue(instance, 'SOPInstanceUID')
      if sopInstanceUid in instancesAlreadyInDatabase:
        # instance is already in database
        continue
      fileName = os.path.join(downloadDirectory, hashlib.md5(sopInstanceUid.encode()).hexdigest() + '.dcm')
      # If the sopinstanceUid is not not already downloaded, download the file 
      if not os.path.isfile(fileName):
        retrievedInstance = self.DICOMwebClient.retrieve_instance(
                                    study_instance_uid=selectedStudy,
                                    series_instance_uid=selectedSeries,
                                    sop_instance_uid=sopInstanceUid)
        # Write the file to the tmp folder 
        pydicom.filewriter.write_file(fileName, retrievedInstance)
    # print ('retrieve_instance(s) in remote database')
        
    # Now add the directory to the DICOM database
    print ('adding the directory to the DICOM database')
    files_saved = [f for f in os.listdir(downloadDirectory) if f.endswith('.dcm')]
    if files_saved: 
      print('add directory')
      indexer.addDirectory(slicer.dicomDatabase, downloadDirectory, True)  # index with file copy
      
      # slicer.util.selectModule("DICOM")
      # browserWidget = slicer.modules.DICOMWidget.browserWidget
      # dicomBrowser = browserWidget.dicomBrowser
      # dicomBrowser.importDirectory(downloadDirectory, dicomBrowser.ImportDirectoryAddLink)
      # dicomBrowser.waitForImportFinished()
      
      # DICOMUtils.importDicom(downloadDirectory,db)
      
      print('indexer wait for import to finish')
      indexer.waitForImportFinished()
      print('slicer process events')
      slicer.app.processEvents()
    
    # Now delete the files from the temporary directory 
    print('delete the files from the temporary directory')
    for f in os.listdir(downloadDirectory):
      os.remove(os.path.join(downloadDirectory, f))
    # Delete the temporary directory 
    os.rmdir(downloadDirectory)
    
    # Now load the newly added files 
    print ('load the newly added files')
    fileList = slicer.dicomDatabase.filesForSeries(selectedSeries)
    print ('fileList: ' + str(fileList))

    # Now load
    print ('now load the volumes')
    # if fileList: 
    import DICOMScalarVolumePlugin
    scalarVolumeReader = DICOMScalarVolumePlugin.DICOMScalarVolumePluginClass()
    loadable = scalarVolumeReader.examineForImport([fileList])[0]
    volume = scalarVolumeReader.load(loadable)
  
    return volume 
    
  
  # def loadVolumeFromRemoteDatabase(self, selectedStudy, selectedSeries):
  #   """ Load a series from a remote DICOM server """
  #
  #   indexer = ctk.ctkDICOMIndexer()        
  #
  #   # A temporary directory for the downloaded DICOM files from the remote database 
  #   downloadDirectory = os.path.join(slicer.dicomDatabase.databaseDirectory, 'tmp')
  #   if not os.path.isdir(downloadDirectory):
  #     # os.mkdir(downloadDirectory)
  #     os.makedirs(downloadDirectory)
  #
  #   # Get the instances corresponding to the chosen study and series  
  #   print ('********** Searching for instances for volumes from remote database *********')    
  #   instances = self.DICOMwebClient.search_for_instances(
  #                         study_instance_uid=selectedStudy,
  #                         series_instance_uid=selectedSeries
  #                         )
  #   # print ('search_for_instances in remote database')
  #
  #   # The instances that are already in the DICOM database, no need to download  
  #   instancesAlreadyInDatabase = slicer.dicomDatabase.instancesForSeries(selectedSeries)
  #
  #   # Download and write the files that are not currently in the DICOM database 
  #   print('downloading and writing the files that are currently not in the DICOM database')
  #   for instanceIndex, instance in enumerate(instances):
  #     sopInstanceUid = instance['00080018']['Value'][0]
  #     if sopInstanceUid in instancesAlreadyInDatabase:
  #       # instance is already in database
  #       continue
  #     fileName = os.path.join(downloadDirectory, hashlib.md5(sopInstanceUid.encode()).hexdigest() + '.dcm')
  #     # If the sopinstanceUid is not not already downloaded, download the file 
  #     if not os.path.isfile(fileName):
  #       retrievedInstance = self.DICOMwebClient.retrieve_instance(
  #                                   study_instance_uid=selectedStudy,
  #                                   series_instance_uid=selectedSeries,
  #                                   sop_instance_uid=sopInstanceUid)
  #       # Write the file to the tmp folder 
  #       pydicom.filewriter.write_file(fileName, retrievedInstance)
  #   # print ('retrieve_instance(s) in remote database')
  #
  #   # Now add the directory to the DICOM database
  #   print ('adding the directory to the DICOM database')
  #   indexer.addDirectory(slicer.dicomDatabase, downloadDirectory, True)  # index with file copy
  #   indexer.waitForImportFinished()
  #
  #   # Now delete the files from the temporary directory 
  #   print('delete the files from the temporary directory')
  #   for f in os.listdir(downloadDirectory):
  #     os.remove(os.path.join(downloadDirectory, f))
  #   # Delete the temporary directory 
  #   os.rmdir(downloadDirectory)
  #
  #   # Now load the newly added files 
  #   print ('load the newly added files')
  #   fileList = slicer.dicomDatabase.filesForSeries(selectedSeries)
  #
  #   # Now load
  #   print ('now load the volumes')
  #   # if fileList: 
  #   import DICOMScalarVolumePlugin
  #   scalarVolumeReader = DICOMScalarVolumePlugin.DICOMScalarVolumePluginClass()
  #   loadable = scalarVolumeReader.examineForImport([fileList])[0]
  #   volume = scalarVolumeReader.load(loadable)
  #
  #   return volume 
  #
  #


  def onStep2Selected(self):
    # if self.currentTabIndex == 2:
    #   self.setCrosshairEnabled(self.refSelector.currentText not in ["", "None"])
    #   return True
    # self.setTabsEnabled([2],True)
    if self.currentTabIndex == 3:
      self.setCrosshairEnabled(self.refSelector.currentText not in ["", "None"])
      return True
    self.setTabsEnabled([3],True)

    checkedItems = [x for x in self.seriesItems if x.checkState()]

    self.volumeNodes = {}
    self.labelNodes = {}
    selectedSeriesNumbers = []
    self.refSeriesNumber = '-1'

    logging.debug('Checked items:')
    ref = None

    self.refSelector.clear()

    # reference selector can have None (initially)
    # user should select reference, which triggers creation of the label and

    # initialization of the editor widget

    self.refSelector.addItem('None')

    # ignore refSelector events until the selector is populated!
    self.refSelectorIgnoreUpdates = True

    # Loading progress indicator
    progress = self.createProgressDialog(maximum=len(checkedItems))
    nLoaded = 0

    # iterate over all selected items and add them to the reference selector
    selectedSeries = {}
    for i in checkedItems:
      text = i.text()

      progress.labelText = text
      progress.setValue(nLoaded)
      slicer.app.processEvents()
      nLoaded += 1

      seriesNumber = text.split(':')[0]
      shortName = self.seriesMap[seriesNumber]['ShortName']
      longName = self.seriesMap[seriesNumber]['LongName']

      # fileName = self.seriesMap[seriesNumber]['NRRDLocation']
      # print("Loading file from "+fileName)
      # volume = slicer.util.loadVolume(fileName)
      
      # This loads from the filepath 
      # filePath = self.seriesMap[seriesNumber]['DICOMLocation']
      # print("Loading files from " + filePath)
      # import DICOMLib.DICOMUtils as utils
      # import DICOMScalarVolumePlugin
      # scalarVolumeReader = DICOMScalarVolumePlugin.DICOMScalarVolumePluginClass()
      # files = [os.path.join(filePath,f) for f in os.listdir(filePath)]
      # loadable = scalarVolumeReader.examineForImport([files])[0]
      # volume = scalarVolumeReader.load(loadable)
      
      
      
      # # Instead load from the DICOM database 
      # db = slicer.dicomDatabase
      # # Get appropriate files 
      # seriesInstanceUID = self.seriesMap[seriesNumber]['seriesInstanceUID']
      # fileList = db.filesForSeries(seriesInstanceUID)
      # # print ('fileList: ' + str(fileList))
      # # Now load
      # import DICOMScalarVolumePlugin
      # scalarVolumeReader = DICOMScalarVolumePlugin.DICOMScalarVolumePluginClass()
      # loadable = scalarVolumeReader.examineForImport([fileList])[0]
      # volume = scalarVolumeReader.load(loadable)
      
      # Load from DICOM database 
      if (self.selectLocalDatabaseButton.isChecked()):
        # print ('Loading volume from local DICOM database')
        studyInstanceUID = self.selectedStudyNumber # added in 
        volume = self.loadVolumeFromLocalDatabase(seriesNumber)
      # Or load from remote server  
      elif (self.selectRemoteDatabaseButton.isChecked() or \
            self.selectOtherRemoteDatabaseButton.isChecked()):
        # print ('Loading volume from remote DICOM server')
        studyInstanceUID = self.selectedStudyNumber
        seriesInstanceUID = self.seriesMap[seriesNumber]['seriesInstanceUID']
        volume = self.loadVolumeFromRemoteDatabase(studyInstanceUID, seriesInstanceUID)
    
        
              
      
      if volume.GetClassName() == 'vtkMRMLScalarVolumeNode':
        self.seriesMap[seriesNumber]['Volume'] = volume
        self.seriesMap[seriesNumber]['Volume'].SetName(shortName)
      elif volume.GetClassName() == 'vtkMRMLMultiVolumeNode':
        self.seriesMap[seriesNumber]['MultiVolume'] = volume
        self.seriesMap[seriesNumber]['MultiVolume'].SetName(shortName+'_multivolume')
        self.seriesMap[seriesNumber]['FrameNumber'] = volume.GetNumberOfFrames()-1
        scalarVolumeNode = MVHelper.extractFrame(None, self.seriesMap[seriesNumber]['MultiVolume'],
                                                       self.seriesMap[seriesNumber]['FrameNumber'])
        scalarVolumeNode.SetName(shortName)
        self.seriesMap[seriesNumber]['Volume'] = scalarVolumeNode
      # self.checkAndLoadLabel(seriesNumber, shortName)
      # self.checkAndLoadLabelDICOM(seriesNumber, shortName) # comment back in when I can load DICOM SEG files.
      # self.checkAndLoadLabelDICOMDatabase(seriesNumber, shortName)
      try:
        if self.seriesMap[seriesNumber]['MetaInfo']['ResourceType'] == 'OncoQuant':
          dNode = volume.GetDisplayNode()
          dNode.SetWindowLevel(5.0,2.5)
          dNode.SetAndObserveColorNodeID('vtkMRMLColorTableNodeFileColdToHotRainbow.txt')
        else:
          self.refSelector.addItem(text)
      except:
        self.refSelector.addItem(text)

      if longName.find('T2')>=0 and longName.find('AX')>=0:
        ref = int(seriesNumber)

      selectedSeries[seriesNumber] = self.seriesMap[seriesNumber]
      logging.debug('Processed '+longName)

      selectedSeriesNumbers.append(int(seriesNumber))

    # self.checkAndLoadLabelDICOMDatabase(seriesNumber, shortName) # add for now 
    self.seriesMap = selectedSeries

    progress.delete()

    logging.debug('Selected series: '+str(selectedSeries)+', reference: '+str(ref))
    #self.cvLogic = CompareVolumes.CompareVolumesLogic()
    #self.viewNames = [self.seriesMap[str(ref)]['ShortName']]

    self.refSelectorIgnoreUpdates = False

    self.checkForMultiVolumes()
    # self.checkForFiducials() # Do this later!! 
    return True

  def onStep3Selected(self):
    self.setCrosshairEnabled(False)
    self.editorWidget.setActiveEffect(None)
    return True

  def checkForFiducials(self):
    self.targetsDir = os.path.join(self.inputDataDir, self.selectedStudyName, 'Targets')
    if not os.path.exists(self.targetsDir):
      return
    mostRecent = ""
    storedTimeStamp = 0
    for filename in [f for f in os.listdir(self.targetsDir) if re.match(self.getSetting('UserName')+"-[0-9]*.fcsv", f)]:
      actualFileName = filename.split(".")[0]
      timeStamp = int(actualFileName.split("-")[1])
      if timeStamp > storedTimeStamp:
        mostRecent = filename
        storedTimeStamp = timeStamp
    self.loadMostRecentFiducialList(mostRecent)

  def loadMostRecentFiducialList(self, mostRecent):
    if mostRecent != "":
      path = os.path.join(self.targetsDir, mostRecent)
      if slicer.util.loadMarkupsFiducialList(path):
        self.fiducialsWidget.currentNode = slicer.util.getFirstNodeByName(mostRecent.split(".")[0])

  def checkForMultiVolumes(self):
    multiVolumes = self.getMultiVolumes()
    self.multiVolumeExplorer.showInputMultiVolumeSelector(len(multiVolumes) > 1)
    multiVolume = None
    if len(multiVolumes) == 1:
      multiVolume = multiVolumes[0]
    elif len(multiVolumes) > 1:
      multiVolume = max(multiVolumes, key=lambda mv: mv.GetNumberOfFrames())
      # TODO: set selector
    self.multiVolumeExplorer.setMultiVolume(multiVolume)
    self.showMultiVolumeExplorer(len(multiVolumes) > 0)

  def showMultiVolumeExplorer(self, show):
    if show:
      self.multiVolumeExplorerArea.show()
    else:
      self.multiVolumeExplorerArea.hide()

  def getMultiVolumes(self):
    multiVolumes = []
    for key, val in self.seriesMap.items():
      if 'MultiVolume' in val.keys():
        multiVolumes.append(val['MultiVolume'])
    return multiVolumes

  def showExitStep3Or4Warning(self):
    result = self.confirmOrSaveDialog('Unsaved contours will be lost!\n\nDo you still want to exit?')
    if result == 1:
      self.onSaveClicked()
    return result == 2

  def setCrosshairEnabled(self, enabled):
    if enabled:
      self.crosshairNode.SetCrosshairMode(slicer.vtkMRMLCrosshairNode.ShowSmallBasic)
      self.crosshairNode.SetCrosshairMode(slicer.vtkMRMLCrosshairNode.ShowSmallBasic)
    else:
      self.crosshairNode.SetCrosshairMode(slicer.vtkMRMLCrosshairNode.NoCrosshair)
      
  def getLatestDICOMSEG(self): 
    '''From the reference series number, find the corresponding labels from the 
       DICOM database. Choose the latest one and load that segmentation. '''
        
    ref = int(self.refSeriesNumber) 
    # print ('ref: ' + str(ref))
    # set the segmentation node to self.seriesMap[str(ref)]['Label'] 
    
    # Get the list of series descriptions and filenames 
    # Keep the ones that have the ref number and label in the name 
    seriesList = slicer.dicomDatabase.seriesForStudy(self.selectedStudyNumber)
    seriesDescriptions = []
    fileNames = [] 
    
    for series in seriesList: 
      fileList = slicer.dicomDatabase.filesForSeries(series)
      fileName = fileList[0]
      seriesDescription = slicer.dicomDatabase.fileValue(fileName, "0008,103e")
      ContentCreatorName = slicer.dicomDatabase.fileValue(fileName, "0070,0084")
      if ("label" in seriesDescription) and \
         (int(seriesDescription.split(':')[0]) == ref) and \
         (ContentCreatorName == self.getSetting('UserName')) :
          seriesDescriptions.append(seriesDescription)
          fileNames.append(fileName)
    
    # No labels exist 
    if not len(fileNames):
      return False,None
            
    # Get the latest file
    for index, seriesDescription in enumerate(seriesDescriptions):
      currentTimeStamp = os.path.getmtime(fileNames[index])
      if (index==0):
        latestTimeStamp = currentTimeStamp
        fileName = fileNames[0] 
        seriesDescription = seriesDescriptions[0]
      else:
        # if the file is newer 
        if (currentTimeStamp > latestTimeStamp):
          latestTimeStamp = currentTimeStamp 
          fileName = fileNames[index]
          seriesDescription = seriesDescriptions[index]
          
          
    ### added ###
    # remove the previous seg nodes with the same name before loading in the latest one.
    seg_nodes_already_exist = slicer.util.getNodesByClass("vtkMRMLSegmentationNode")
    # print ('seg nodes that already exist: ' + str(len(seg_nodes_already_exist)))
    seg_names = [] 
    for seg_node in seg_nodes_already_exist:
      seg_name = seg_node.GetName() 
      if (seg_name==seriesDescription):
        slicer.mrmlScene.RemoveNode(seg_node)
    #############
    
    
    # Load the segmentation file 
    DICOMSegmentationPlugin = slicer.modules.dicomPlugins['DICOMSegmentationPlugin']()
    loadables = DICOMSegmentationPlugin.examineFiles([fileName])
    DICOMSegmentationPlugin.load(loadables[0])
    
    # create seriesMap 
    # self.refSeriesNumber = seriesDescription.split(':')[0] # should be 6 
    # ref = int(self.refSeriesNumber) # 6
    refLabel = slicer.util.getNode(seriesDescription) # seriesDescription should be '6:T2 Weighted Axial-label'
    self.seriesMap[str(ref)]['Label'] = refLabel 
    
    return True       
  
  
  def getLatestDICOMSEGRemote(self): 
    '''From the reference series number, find the corresponding labels from the 
       remote server. Choose the latest one and load that segmentation. '''
        
    indexer = ctk.ctkDICOMIndexer()  
        
    ref = int(self.refSeriesNumber) 
    # print ('ref: ' + str(ref))
    # set the segmentation node to self.seriesMap[str(ref)]['Label'] 
    
    # Get the meta data for the self.selectedStudyNumber 
    # metadata = client.retrieve_study_metadata('1.2.826.0.1.3680043.8.1055.1.20111103111148288.98361414.79379639')

    # Get the study selected
    studyInstanceUID = self.selectedStudyNumber
    # Get the list of series  
    # seriesList = self.DICOMwebClient.search_for_series(studyInstanceUID) # should not call this again?
    # print ('seriesList: ' + str(seriesList)) 
    # print ('search_for_studies (seg) in remote database')
    
    
    # seriesList_label = [] 
    seriesDescriptions = [] 
    seriesInstanceUIDs_label = [] 
    sopInstanceUIDs = [] 
    ContentDates = []
    ContentTimes = [] 
    
    print ('*******Getting the latest DICOM SEG files from remote*******')
    
    # for series in seriesList:
    for series in self.seriesList:  
    
    
      # seriesNumber = series['00200011']['Value'][0] # seriesNumber doesn't exist.. 
      # need to get metadata 
      # seriesInstanceUID = series['00081030']['Value'][0]
      
      seriesInstanceUID = series['0020000E']['Value'][0]
      # seriesInstanceUID = self.seriesMap[str(ref)]['seriesInstanceUID'] 
      
      
      
      metadata = self.DICOMwebClient.retrieve_series_metadata(study_instance_uid=studyInstanceUID,
                                                              series_instance_uid=seriesInstanceUID
                                                              )
      # print ('metadata[0]: ' + str(metadata[0]))
      seriesNumber = str(metadata[0]['00200011']['Value'][0])
      # seriesInstanceUID = series['00081030']['Value'][0]
      seriesDescription = series['0008103E']['Value'][0]
      # seriesDescription = self.seriesMap[str(ref)]['LongName']
      
      ShortName = str(seriesNumber)+":"+seriesDescription
            
      # ContentCreatorName = series['00700084']['Value'][0] # check this -- only in the SEG file 
      # ContentCreatorName = slicer.dicomDatabase.fileValue(fileName, "0070,0084")
      # if ("label" in seriesDescription) and \
      #    (int(seriesDescription.split(':')[0]) == ref) and \
      #    (ContentCreatorName == self.getSetting('UserName')) :
      #     seriesDescriptions.append(seriesDescription)
      if ("label" in seriesDescription) and \
          (int(seriesDescription.split(':')[0]) == ref):
        ContentCreatorName = metadata[0]['00700084']['Value'][0]['Alphabetic']
        ContentDate = metadata[0]['00080023']['Value'][0]
        ContentTime = metadata[0]['00080033']['Value'][0]
        sopInstanceUID = metadata[0]['00080018']['Value'][0] 
        if (ContentCreatorName == self.getSetting('UserName')): 
          seriesInstanceUIDs_label.append(seriesInstanceUID)
          seriesDescriptions.append(seriesDescription)
          sopInstanceUIDs.append(sopInstanceUID)
          ContentDates.append(ContentDate)
          ContentTimes.append(ContentTime)
          
          

      
    # print ('retrieve_series_metadata (seg) in remote database')
          
    # No labels exist 
    if not len(seriesInstanceUIDs_label):
      return False,None
    
    # Get the latest file - the last label file with the username that was added to the dicom data store 
    for index, series in enumerate(seriesInstanceUIDs_label):
      ContentDate = ContentDates[index]
      ContentTime = ContentTimes[index]
      currentTimeStamp = datetime.datetime.strptime(ContentDate+ContentTime, "%Y%m%d%H%M%S").timestamp()
      if (index==0):
        latestTimeStamp = currentTimeStamp
        seriesInstanceUID = seriesInstanceUIDs_label[0]
        seriesDescription = seriesDescriptions[0]
        sopInstanceUID = sopInstanceUIDs[0]
      else:
        # if the file is newer 
        if (currentTimeStamp > latestTimeStamp):
          latestTimeStamp = currentTimeStamp 
          seriesInstanceUID = seriesInstanceUIDs_label[index]
          seriesDescription = seriesDescriptions[index]
          sopInstanceUID = sopInstanceUIDs[index]
          
    
    print ('******** Getting the matching DICOM SEG instance from remote *********')
    
    # Retrieve the instance using the DICOM web client  
    retrievedInstance = self.DICOMwebClient.retrieve_instance(study_instance_uid=studyInstanceUID,
                                                              series_instance_uid=seriesInstanceUID, 
                                                              sop_instance_uid=sopInstanceUID)
    # print ('retrieve_instance (seg) from remote database')
    # Save to here for now 
    db = slicer.dicomDatabase
    # labelSeries = label.GetName().split(':')[0] # fix 
    labelSeries = str(ref) # should be right 
    # segmentationsDir = os.path.join(db.databaseDirectory, self.selectedStudyName, labelSeries) 
    # self.logic.createDirectory(segmentationsDir)
    # # labelFileName = os.path.join(segmentationsDir, 'subject_hierarchy_export.SEG'+exporter.currentDateTime+".dcm")
    # print ('segmentationsDir: ' + segmentationsDir)
    segmentationsDir = os.path.join(slicer.dicomDatabase.databaseDirectory, 'tmp') 
    self.logic.createDirectory(segmentationsDir)
    # print ('segmentationsDir: ' + segmentationsDir)
    
    
    ### added ###
    # remove the previous seg nodes with the same name before loading in the latest one.
    seg_nodes_already_exist = slicer.util.getNodesByClass("vtkMRMLSegmentationNode")
    # print ('seg nodes that already exist: ' + str(len(seg_nodes_already_exist)))
    seg_names = [] 
    for seg_node in seg_nodes_already_exist:
      seg_name = seg_node.GetName() 
      if (seg_name==seriesDescription):
        slicer.mrmlScene.RemoveNode(seg_node)
    #############
    
    
    # Write the SEG file 
    import DICOMSegmentationPlugin 
    exporter = DICOMSegmentationPlugin.DICOMSegmentationPluginClass()
    # DICOMSegmentationPlugin = slicer.modules.dicomPlugins['DICOMSegmentationPlugin']()
    fileName = os.path.join(segmentationsDir, 'subject_hierarchy_export.SEG'+exporter.currentDateTime+".dcm")
    # print ('fileName: ' + fileName)
    # import pydicom 
    pydicom.filewriter.write_file(fileName, retrievedInstance)
    
    # Add the tmp directory to the local DICOM database 
    indexer.addDirectory(slicer.dicomDatabase, segmentationsDir, True)  # index with file copy
    indexer.waitForImportFinished()
    
    # Now delete the files from the temporary directory 
    for f in os.listdir(segmentationsDir):
      os.remove(os.path.join(segmentationsDir, f))
    # Delete the temporary directory 
    os.rmdir(segmentationsDir)
    
    # # Now load the newly added files 
    # fileList = slicer.dicomDatabase.filesForSeries(selectedSeries)
    #
    # # Now load
    # import DICOMScalarVolumePlugin
    # scalarVolumeReader = DICOMScalarVolumePlugin.DICOMScalarVolumePluginClass()
    # loadable = scalarVolumeReader.examineForImport([fileList])[0]
    # volume = scalarVolumeReader.load(loadable)
    #
    # return volume 
  
    # Now need to load the DICOM SEG from the local DICOM database, and not 
    # from the file that was just saved out and deleted
    fileList = slicer.dicomDatabase.filesForSeries(seriesInstanceUID)
    fileName = fileList[0]
  
    
    
    # Load the SEG file 
    # loadables = DICOMSegmentationPlugin.examineFiles([fileName])
    # DICOMSegmentationPlugin.load(loadables[0])
    loadables = exporter.examineFiles([fileName])
    exporter.load(loadables[0])
    
    # create seriesMap 
    # refLabel = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode", seriesDescription) # is this right though? why was it created before?
    refLabel = slicer.util.getNode(seriesDescription) # seriesDescription should be '6:T2 Weighted Axial-label'
    self.seriesMap[str(ref)]['Label'] = refLabel 
    
    return True   
  
  
    # import DICOMSegmentationPlugin
    # exporter = DICOMSegmentationPlugin.DICOMSegmentationPluginClass()
  
    # # Load the segmentation file 
    # DICOMSegmentationPlugin = slicer.modules.dicomPlugins['DICOMSegmentationPlugin']()
    # loadables = DICOMSegmentationPlugin.examineFiles([fileName])
    # DICOMSegmentationPlugin.load(loadables[0])
  

  def onReferenceChanged(self, id):
    # TODO: when None is selected, viewers and editor should be resetted
    self.labelMapVisibilityButton.checked = False
    if self.refSelectorIgnoreUpdates:
      return
    text = self.refSelector.currentText
    eligible = text not in ["", "None"]
    self.setCrosshairEnabled(eligible)
    logging.debug('Current reference node: '+text)
    
    if eligible:
      self.refSeriesNumber = text.split(':')[0]
      ref = int(self.refSeriesNumber)
    else:
      return
    
    self.refSeriesNumber = text.split(':')[0]
    ref = int(self.refSeriesNumber)

    logging.debug('Reference series selected: '+str(ref))

    # volume nodes ordered by series number
    seriesNumbers= [int(x) for x in self.seriesMap.keys()]
    seriesNumbers.sort()
    self.volumeNodes = [self.seriesMap[str(x)]['Volume'] for x in seriesNumbers if x != ref]
    self.viewNames = [self.seriesMap[str(x)]['ShortName'] for x in seriesNumbers if x != ref]

    self.volumeNodes = [self.seriesMap[str(ref)]['Volume']]+self.volumeNodes
    self.viewNames = [self.seriesMap[str(ref)]['ShortName']]+self.viewNames

    self.sliceNames = [str(x) for x in seriesNumbers if x != ref]
    self.sliceNames = [str(ref)]+self.sliceNames
    
    # Added
    # Load the latest DICOM SEG file from the DICOM database according to the reference chosen 
    # set the self.seriesMap[str(ref)]['Label'] to be equal to the segmentation node 
    
    # self.getLatestDICOMSEG()
    
    if (self.selectLocalDatabaseButton.isChecked()):
      self.getLatestDICOMSEG()
    elif (self.selectRemoteDatabaseButton.isChecked() or self.selectOtherRemoteDatabaseButton.isChecked()):
      self.getLatestDICOMSEGRemote()
    

    try:
      # check if already have a label for this node
      refLabel = self.seriesMap[str(ref)]['Label']
      
    except KeyError:
      # create a new label
      labelName = self.seriesMap[str(ref)]['ShortName']+'-label'
      
      # ### added ###
      # seg_nodes_already_exist = slicer.util.getNodesByClass("vtkMRMLSegmentationNode")
      # print ('seg nodes that already exist: ' + str(len(seg_nodes_already_exist)))
      # seg_names = [] 
      # for seg_node in seg_nodes_already_exist:
      #   seg_name = seg_node.GetName() 
      #   if (seg_name==labelName):
      #     slicer.mrmlScene.RemoveNode(seg_node)
      # #############
      
      refLabel = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode", labelName)
      self.seriesMap[str(ref)]['Label'] = refLabel

    # dNode = refLabel.GetDisplayNode()
    # dNode.SetAndObserveColorNodeID(self.mpReviewColorNode.GetID())
    logging.debug('Volume nodes: '+str(self.viewNames))
    self.cvLogic = CompareVolumes.CompareVolumesLogic()

    nVolumeNodes = float(len(self.volumeNodes))
    self.rows = 0
    self.cols = 0
    if nVolumeNodes == 1:
      self.rows = 1
    elif nVolumeNodes<=8:
      self.rows = 2 # up to 8
    elif 8 < nVolumeNodes <= 12:
      self.rows = 3 # up to 12
    elif 12 < nVolumeNodes <= 16:
      self.rows = 4
    self.cols = math.ceil(nVolumeNodes/self.rows)

    self.editorWidget.setSegmentationNode(self.seriesMap[str(ref)]['Label'])
    self.editorWidget.setMasterVolumeNode(self.volumeNodes[0])
    
    ### For each segment that is already present in the segmentationNode, set the terminology entry to the one I want ###
    # Get list of segments 
    segmentationNode = self.seriesMap[str(ref)]['Label']
    segmentIds = segmentationNode.GetSegmentation().GetSegmentIDs() 
    for segmentId in segmentIds: 
      # Set the terminology entry 
      segment = segmentationNode.GetSegmentation().GetSegment(segmentId)
      segment.SetTag(slicer.vtkSegment.GetTerminologyEntryTagName(),
                     self.editorWidget.defaultTerminologyEntry)

    self.cvLogic.viewerPerVolume(self.volumeNodes, background=self.volumeNodes[0], label=refLabel,
                                 layout=[self.rows,self.cols],viewNames=self.sliceNames,
                                 orientation=self.currentOrientation)

    # Make sure redslice has the ref image (the others were set with viewerPerVolume)
    redSliceWidget = self.layoutManager.sliceWidget('Red')
    redSliceNode = redSliceWidget.mrmlSliceNode()
    redSliceNode.SetOrientation(self.currentOrientation)
    compositeNode = redSliceWidget.mrmlSliceCompositeNode()
    compositeNode.SetBackgroundVolumeID(self.volumeNodes[0].GetID())

    self.cvLogic.rotateToVolumePlanes(self.volumeNodes[0])
    self.setOpacityOnAllSliceWidgets(1.0)
    self.editorWidget.segmentationNode().GetDisplayNode().SetVisibility2DFill(not self.labelMapOutlineButton.checked)
    # self.editorWidget.segmentationNode().AddObserver(slicer.vtkSegmentation.SegmentAdded, self.onSegmentAdded)

    self.onViewUpdateRequested(self.viewButtonGroup.checkedId())
    
    logging.debug('Setting master node for the Editor to '+self.volumeNodes[0].GetID())

    # # default to selecting the first available structure for this volume
    # if self.editorWidget.helper.structureListWidget.structures.rowCount() > 0:
    #   self.editorWidget.helper.structureListWidget.selectStructure(0)

    self.multiVolumeExplorer.refreshObservers()
    logging.debug('Exiting onReferenceChanged')
    
    # Added
    # Link the slice views
    # links the scrolling, but not the zoom and pan 
    sliceCompositeNodes = slicer.util.getNodesByClass("vtkMRMLSliceCompositeNode")
    for sliceCompositeNode in sliceCompositeNodes:
      sliceCompositeNode.HotLinkedControlOn()
      sliceCompositeNode.LinkedControlOn()
      # sliceCompositeNode.SetHotLinkedControl(True)
      # sliceCompositeNode.SetLinkedControl(True)
    


      return

  '''
  def updateViews(self):
    lm = slicer.app.layoutManager()
    w = lm.sliceWidget('Red')
    sl = w.sliceLogic()
    ll = sl.GetLabelLayer()
    lv = ll.GetVolumeNode()
    self.cvLogic.viewerPerVolume(self.volumeNodes, background=self.volumeNodes[0], label=lv,
                                 layout=[self.rows,self.cols])

    self.cvLogic.rotateToVolumePlanes(self.volumeNodes[0])
    self.setOpacityOnAllSliceWidgets(1.0)
  '''

  def setOrientation(self, orientation):
    if orientation in self.orientations:
      self.currentOrientation = orientation

      if self.refSelector.currentText != 'None':
        # set slice node orientation
        for widget in self.getAllSliceWidgets():
          node = widget.mrmlSliceNode()
          node.SetOrientation(self.currentOrientation)

        self.cvLogic.rotateToVolumePlanes(self.volumeNodes[0])

  def onSliderChanged(self, newValue):
    newValue = int(newValue)
    seriesNumber = self.multiVolumeExplorer.getCurrentSeriesNumber()
    if seriesNumber in self.seriesMap.keys():
      multiVolumeNode = self.seriesMap[seriesNumber]['MultiVolume']
      scalarVolumeNode = MVHelper.extractFrame(self.seriesMap[seriesNumber]['Volume'],
                                                               multiVolumeNode,
                                                               newValue)
      scalarVolumeNode.SetName(multiVolumeNode.GetName().split('_multivolume')[0])
      self.seriesMap[seriesNumber]['Volume'] = scalarVolumeNode
      self.seriesMap[seriesNumber]['FrameNumber'] = newValue
      multiVolumeNode.GetDisplayNode().SetFrameComponent(newValue)

  def getCreatedStructures(self):
    # TODO: usually not all structures shall be available for fiducial creation
    itemModel = self.editorWidget.helper.structureListWidget.structures
    structures = []
    for row in range(itemModel.rowCount()):
      item = dict()
      item["Number"] = itemModel.item(row, 0).text()
      item["Name"] = itemModel.item(row, 2).text()
      item["LabelVolume"] = self.editorWidget.helper.structureListWidget.structures.item(row, 3).text()
      structures.append(item)
    return structures

  def onFiducialPromptClosed(self):
    pass  #self.structuresView.disconnect("activated(QModelIndex)", self.onStructureClickedOrAdded)

  def onStructureClickedOrAdded(self):
    structures = self.getCreatedStructures()
    if len(self.structures) != len(structures):
      self.structures = self.getCreatedStructures()

  def selectAllSeries(self, selected=False):
    for item in self.seriesItems:
      item.setCheckState(2 if selected else 0)
    # self.setTabsEnabled([1], selected)
    self.setTabsEnabled([2], selected)

  def restoreForeground(self):
    # This relies on slice view names and also (apparently) trashes zoom levels
    # Is there a better way to do this?
    for view in self.layoutManager.sliceViewNames():
      widget = self.layoutManager.sliceWidget(view)
      compositeNode = widget.mrmlSliceCompositeNode()
      try:
        compositeNode.SetForegroundVolumeID(self.seriesMap[view]['Volume'].GetID())
      except:
        pass

  # Gets triggered on a click in the structures table
  def onStructureClicked(self, segmentID):
    self.labelMapVisibilityButton.checked = False

class mpReviewLogic(ScriptedLoadableModuleLogic):
  """This class should implement all the actual
  computation done by your module.  The interface
  should be such that other python code can import
  this class and make use of the functionality without
  requiring an instance of the Widget
  """

  @staticmethod
  def wasmpReviewPreprocessed(directory):
    return len(mpReviewLogic.getStudyNames(directory)) > 0

  @staticmethod
  def getStudyNames(directory):
    def getSubDirectories(currentDirectory):
      return [d for d in os.listdir(currentDirectory) if os.path.isdir(os.path.join(currentDirectory, d))]
    return [d for d in getSubDirectories(directory) if "RESOURCES" in getSubDirectories(os.path.join(directory, d))]

  @staticmethod
  def getStudyNamesDICOMDatabase():
    db = slicer.dicomDatabase
    patientList = list(db.patients())
    studiesMap = {} 
    studyListAll = [] 
    for patient in range(0,len(patientList)):
      studyList = db.studiesForPatient(patientList[patient])
      # print ('studyList: ' + str(studyList))
      for index, study in enumerate(studyList):
          # print ('index: ' + str(index))
          # print ('study: ' + str(study))
          seriesList = db.seriesForStudy(study)
          fileList = db.filesForSeries(seriesList[0])
          # ShortName = PatientName_studyDate
          ShortName = db.fileValue(fileList[0], "0010,0010") + '_' + db.fileValue(fileList[0], "0008,0020")
          # studiesMap[index] = {'ShortName': ShortName}
          studiesMap[study] = {'ShortName': ShortName}
          # LongName = SeriesDescription 
          # studiesMap[index]['LongName'] = db.fileValue(fileList[0], "0008,1030")
          studiesMap[study]['LongName'] = db.fileValue(fileList[0], "0008,1030")
          # studiesMap[index]['StudyInstanceUID'] = study 
          studiesMap[study]['StudyInstanceUID'] = study 
          
      # if (len(studyList)>1):
      #   studyListAll.append([d for d in studyList])
      # else:
      #   studyListAll.append(studyList[0])
        
    # return studyListAll 
    return studiesMap 
    
    # studiesMap = {}
    # studiesNumber 
    # studiesMap[seriesNumber] = {'MetaInfo':None, 'DICOMLocation':dicomFilesDirectory,'LongName':seriesDescription, 
    #                             'patientName':patientName, 'studyInstanceUID':studyInstanceUID, 'seriesInstanceUID':seriesInstanceUID}
    # studiesMap[seriesNumber]['ShortName'] = str(seriesNumber)+":"+seriesDescription


  

  @staticmethod
  def createDirectory(directory, message=None):
    if message:
      logging.debug(message)
    try:
      os.makedirs(directory)
    except OSError:
      logging.debug('Failed to create the following directory: ' + directory)

  @staticmethod
  def cleanupDir(d):
    if not os.path.exists(d):
      return
    oldFiles = os.listdir(d)
    for f in oldFiles:
      path = os.path.join(d, f)
      if not os.path.isdir(path):
        os.unlink(d+'/'+f)

  @staticmethod
  def isSeriesOfInterest(desc):
    discardThose = ['SAG','COR','PURE','mapping','DWI',
                    'breath','3D DCE','loc','Expo','Map',
                    'MAP','POST','ThreeParameter','AutoAIF',
                    'BAT','-Slope','PkRsqr','Loc','Cal','Body']
    for d in discardThose:
      if desc.find(d)>=0:
        return False
    return True

  @staticmethod
  def abbreviateName(meta):
    try:
      description = meta['SeriesDescription']
      seriesNumber = meta['SeriesNumber']
    except:
      description = meta['DerivedSeriesDescription']
      seriesNumber = meta['DerivedSeriesNumber']
    abbr = 'Unknown'

    substrAbbreviation = {'Apparent Diffusion Coeff': 'ADC', 'T2':'T2', 'T1':'T1', 'Ktrans':'Ktrans', 'Ve':'ve',
                          'MaxSlope':'MaxSlope', 'TTP':'TTp', 'Auc':'AUC', }

    for substring, abbreviation in iter(substrAbbreviation.items()):
      if substring in description:
        abbr = abbreviation
    if re.search('[a-zA-Z]',description) is None:
      abbr = 'Subtract'
    return seriesNumber+'-'+abbr

  def __init__(self, parent=None):
    ScriptedLoadableModuleLogic.__init__(self, parent)


  @staticmethod
  def loadMpReviewProcessedData(resourcesDir, updateProgressCallback=None):
    loadFurtherInformation = False # True

    sourceFile = None

    nLoaded = 0
    seriesMap = {}
    for root, dirs, files in os.walk(resourcesDir):
      logging.debug('Root: '+root+', files: '+str(files))
      resourceType = os.path.split(root)[1] 
      logging.debug('Resource: '+resourceType)
      
      print ('resourceType: ' + resourceType)

      if resourceType == 'Reconstructions':
        seriesNumber = None
        seriesDescription = None

        # mpReviewPreprocessor generated tree
        for currentXMLFile in [f for f in files if f.endswith('.xml')]:
          metaFile = os.path.join(root, currentXMLFile)
          logging.debug('Current XML File: ' + metaFile)
          try:
            (seriesNumber, seriesDescription) = mpReviewLogic.getSeriesInfoFromXML(metaFile)
            logging.debug(str(seriesNumber)+' '+seriesDescription)
          except Exception as exc:
            logging.error('Failed to get from XML: %s' % str(exc))
            continue

        # mpReviewPreprocessor2 generated tree
        if seriesNumber is None or seriesDescription is None:
          for currentJSONFile in [f for f in files if f.endswith('.json')]:
            metaFile = os.path.join(root, currentJSONFile)
            try:
              bidsJSON = json.load(open(metaFile))
              seriesNumber = str(bidsJSON["SeriesNumber"])
              seriesDescription = mpReviewLogic.normalizeSeriesDescription(bidsJSON["SeriesDescription"])
            except Exception as exc:
              logging.error('Failed to get from JSON: %s' % str(exc))

          if updateProgressCallback:
            updateProgressCallback(labelText=seriesDescription, value=nLoaded)
          nLoaded += 1

        volumePath = None
        reconDirFiles = os.listdir(root)
        # considering there may be different paths to reconstruction, take the
        # first suitable format
        for f in reconDirFiles:
          if f.endswith(".nrrd")>0 or f.endswith(".nii")>0 or f.endswith(".nii.gz")>0:
            volumePath = os.path.join(root, f)
            break

        if volumePath is None:
          logging.error("Failed to find reconstructed volume file.")
          continue

        seriesMap[seriesNumber] = {'MetaInfo':None, 'NRRDLocation':volumePath,'LongName':seriesDescription}
        seriesMap[seriesNumber]['ShortName'] = str(seriesNumber)+":"+seriesDescription

        canonicalFile = os.path.join(os.path.split(root)[0], "Canonical", seriesNumber+".json")
        try:
          canonicalDict = json.load(open(canonicalFile))
          if "SeriesTypeAnnotation" in canonicalDict.keys():
            seriesMap[seriesNumber]['SeriesTypeAnnotation'] = canonicalDict['SeriesTypeAnnotation']
            print("Setting SeriesTypeAnnotation to "+canonicalDict['SeriesTypeAnnotation']+" for series "+seriesNumber)
        except (OSError, IOError) as e:
          pass

        if loadFurtherInformation is True:
          sourceFile = metaFile
          loadFurtherInformation = False
          

      # ignore the PK maps for the purposes of segmentation
      if resourceType == 'OncoQuant' and False:
        for f in files:
          if f.endswith('.json'):
            metaFile = open(os.path.join(root,f))
            metaInfo = json.load(metaFile)
            logging.debug('JSON meta info: '+str(metaInfo))
            try:
              seriesNumber = metaInfo['SeriesNumber']
              seriesDescription = metaInfo['SeriesDescription']
            except:
              seriesNumber = metaInfo['DerivedSeriesNumber']
              seriesDescription = metaInfo['ModelType']+'-'+metaInfo['AIF']+'-'+metaInfo['Parameter']
            volumePath = os.path.join(root,seriesNumber+'.nrrd')
            seriesMap[seriesNumber] = {'MetaInfo':metaInfo, 'NRRDLocation':volumePath,'LongName':seriesDescription}
            seriesMap[seriesNumber]['ShortName'] = str(seriesNumber)+":" + \
                                                   mpReviewLogic.abbreviateName(seriesMap[seriesNumber]['MetaInfo'])



    logging.debug('All series found: '+str(seriesMap.keys()))
    return seriesMap, sourceFile

  @staticmethod 
  def loadMpReviewProcessedDataDICOM(resourcesDir, updateProgressCallback=None):
      
    loadFurtherInformation = False # True
    sourceFile = None
    nLoaded = 0
    seriesMap = {}
    
    for root, dirs, files in os.walk(resourcesDir):
        
        logging.debug('Root: '+root+', files: '+str(files))
        resourceType = os.path.split(root)[1] 
        logging.debug('Resource: '+resourceType)
                
        if resourceType == 'DICOM':
        
            dicomFilesDirectory = root
            print ('dicomFilesDirectory: ' + dicomFilesDirectory)
            # Get series number 
            seriesNumber = os.path.basename(os.path.dirname(root))
            print ('seriesNumber: ' + str(seriesNumber))
            # Get series description 
            import pydicom 
            fileList = os.listdir(dicomFilesDirectory)
            ds = pydicom.dcmread(os.path.join(dicomFilesDirectory,fileList[0]))
            patientName = ds[0x0010,0x0010].value
            studyInstanceUID = ds[0x0020,0x000d].value
            seriesInstanceUID = ds[0x0020,0x000e].value
            seriesDescription = ds[0x0008,0x103e].value
            print ('patientName: ' + str(patientName))
            print ('studyInstanceUID: ' + str(studyInstanceUID))
            print ('seriesInstanceUID: ' + str(seriesInstanceUID))
            print ('seriesDescription: ' + str(seriesDescription))
            # seriesMap[seriesNumber] = {'MetaInfo':None, 'NRRDLocation': dicomFilesDirectory,'LongName':seriesDescription}
            # seriesMap[seriesNumber] = {'MetaInfo':None, 'DICOMLocation': dicomFilesDirectory,'LongName':seriesDescription}
            seriesMap[seriesNumber] = {'MetaInfo':None, 'DICOMLocation':dicomFilesDirectory,'LongName':seriesDescription, 
                                       'patientName':patientName, 'studyInstanceUID':studyInstanceUID, 'seriesInstanceUID':seriesInstanceUID}
            seriesMap[seriesNumber]['ShortName'] = str(seriesNumber)+":"+seriesDescription
            
            # # Need to add to the DICOM database
            # # instantiate a new DICOM browser
            # slicer.util.selectModule("DICOM")
            # dicomBrowser = slicer.modules.DICOMWidget.browserWidget.dicomBrowser
            # # use dicomBrowser.ImportDirectoryCopy to make a copy of the files (useful for importing data from removable storage)
            # dicomBrowser.importDirectory(dicomFilesDirectory, dicomBrowser.ImportDirectoryAddLink)
            # # wait for import to finish before proceeding (optional, if removed then import runs in the background)
            # dicomBrowser.waitForImportFinished()
            
            from DICOMLib import DICOMUtils
            db = slicer.dicomDatabase
            DICOMUtils.importDicom(dicomFilesDirectory,db)
        
    return seriesMap, sourceFile

  @staticmethod
  def getSeriesInfoFromXML(f):

    def findElement(dom, name):
      els = dom.getElementsByTagName('element')
      for e in els:
        if e.getAttribute('name') == name:
          return e.childNodes[0].nodeValue

    dom = xml.dom.minidom.parse(f)
    number = findElement(dom, 'SeriesNumber')
    name = self.normalizeSeriesDescription(findElement(dom, 'SeriesDescription').encode('utf-8').strip())
    return number, name

  @staticmethod
  def normalizeSeriesDescription(name):
    import re
    pattern = re.compile('[^a-zA-Z0-9_ ]')
    normalized_name = pattern.sub('_', name)
    return normalized_name

  def formatDate(self, extractedDate):
    formatted = datetime.date(int(extractedDate[0:4]), int(extractedDate[4:6]), int(extractedDate[6:8]))
    return formatted.strftime("%Y-%b-%d")

  def hasImageData(self,volumeNode):
    """This is a dummy logic method that
    returns true if the passed in volume
    node has valid image data
    """
    if not volumeNode:
      logging.debug('no volume node')
      return False
    if volumeNode.GetImageData() is None:
      logging.debug('no image data')
      return False
    return True


class mpReviewMultiVolumeExplorer(qSlicerMultiVolumeExplorerSimplifiedModuleWidget):

  def __init__(self, parent=None):
    qSlicerMultiVolumeExplorerSimplifiedModuleWidget.__init__(self, parent)

  def getCurrentSeriesNumber(self):
    ref = -1
    if self._bgMultiVolumeNode:
      name = self._bgMultiVolumeNode.GetName()
      ref = name.split(':')[0]
    return ref
  def showInputMultiVolumeSelector(self, show):
    if show:
      self._bgMultiVolumeSelectorLabel.show()
      self.bgMultiVolumeSelector.show()
    else:
      self._bgMultiVolumeSelectorLabel.hide()
      self.bgMultiVolumeSelector.hide()

  def setMultiVolume(self, node):
    self.bgMultiVolumeSelector.setCurrentNode(node)

  def setupConnections(self):
    qSlicerMultiVolumeExplorerSimplifiedModuleWidget.setupConnections(self)

  def createChart(self, sliceWidget, position):
    self._multiVolumeIntensityChart.createChart(sliceWidget, position, ignoreCurrentBackground=True)

  def refreshGUIForNewBackgroundImage(self):
    self._multiVolumeIntensityChart.reset()
    self.setFramesEnabled(True)
    self.refreshFrameSlider()
    self._multiVolumeIntensityChart.bgMultiVolumeNode = self._bgMultiVolumeNode

  def onBackgroundInputChanged(self):
    qSlicerMultiVolumeExplorerSimplifiedModuleWidget.onBackgroundInputChanged(self)
    self.popupChartButton.setEnabled(self._bgMultiVolumeNode is not None)

  def onSliderChanged(self, frameId):
    return
