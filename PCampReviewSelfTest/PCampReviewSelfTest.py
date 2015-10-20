import os
import unittest
import vtk, qt, ctk, slicer
from slicer.ScriptedLoadableModule import *
import logging


class PCampReviewSelfTest(ScriptedLoadableModule):

  def __init__(self, parent):
    ScriptedLoadableModule.__init__(self, parent)
    self.parent.title = "PCampReviewSelfTest"
    self.parent.categories = ["Testing.TestCases"]
    self.parent.dependencies = ["PCampReview"]
    self.parent.contributors = ["Christian Herz (SPL)"]
    self.parent.helpText = """
    This selftest is designed for testing functionality of module PCampReview.
    """
    self.parent.acknowledgementText = """
    Supported by NIH U01CA151261 (PI Fennessy)
    """


class PCampReviewSelfTestWidget(ScriptedLoadableModuleWidget):

  def setup(self):
    ScriptedLoadableModuleWidget.setup(self)

    # Instantiate and connect widgets ...

    #
    # Parameters Area
    #
    parametersCollapsibleButton = ctk.ctkCollapsibleButton()
    parametersCollapsibleButton.text = "Parameters"
    self.layout.addWidget(parametersCollapsibleButton)

    # Layout within the dummy collapsible button
    parametersFormLayout = qt.QFormLayout(parametersCollapsibleButton)

    # Apply Button
    #
    self.applyButton = qt.QPushButton("Apply")
    self.applyButton.toolTip = "Run the algorithm."
    self.applyButton.enabled = True
    parametersFormLayout.addRow(self.applyButton)

    # connections
    self.applyButton.connect('clicked(bool)', self.onApplyButton)

    # Add vertical spacer
    self.layout.addStretch(1)

  def cleanup(self):
    pass

  def onApplyButton(self):
    logic =PCampReviewSelfTestLogic()
    print("Run the test algorithm")
    logic.run()


class PCampReviewSelfTestLogic(ScriptedLoadableModuleLogic):

  def run(self):
    """
    Run the actual algorithm
    """
    # start in the colors module
    m = slicer.util.mainWindow()
    m.moduleSelector().selectModule('PCampReview')
    self.delayDisplay('Switched to PCampReview module')

    '''
    1. download sample data
    2. set directory as input
    3. should fail to load and show prompt for executing preprocessor
    4. (study list updated)
    5. select first study
    6. make sure that then some series are selected
    7. go to segmentation tab
    8. select reference image
    9. create label
    10. create fiducial from label
    11. save everything
    '''

    return True


class PCampReviewSelfTestTest(ScriptedLoadableModuleTest):

  def setUp(self):
    """ Do whatever is needed to reset the state - typically a scene clear will be enough.
    """
    slicer.mrmlScene.Clear(0)

  def runTest(self):
    """Run as few or as many tests as needed here.
    """
    self.setUp()
    self.test_PCampReviewSelfTestTest1()

  def test_PCampReviewSelfTestTest1(self):

    self.delayDisplay("Starting the scalarbar test")

    logic = PCampReviewSelfTestLogic()
    logic.run()

    self.delayDisplay('Test passed!')