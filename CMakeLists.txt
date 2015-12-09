cmake_minimum_required(VERSION 3.0.1)

#-----------------------------------------------------------------------------
set(EXTENSION_NAME mpReview)
set(EXTENSION_HOMEPAGE "http://wiki.slicer.org/slicerWiki/index.php/Documentation/Nightly/Extensions/mpReview")
set(EXTENSION_CATEGORY "Informatics")
set(EXTENSION_CONTRIBUTORS "Andrey Fedorov (SPL), Robin Weiss (U. of Chicago), Alireza Mehrtash (SPL), Christian Herz (SPL)")
set(EXTENSION_DESCRIPTION "Multiparametric Image Review (mpReview) module is intended to support review and annotation of multiparametric image data. The driving use case for the development of this module was review and segmentation of the regions of interest in prostate cancer multiparametric MRI. This work is done as part of the Quantitative Imaging Network (QIN) and Informatics Technology for Cancer Research (ITCR) initiatives of the National Cancer Institute, and is funded by the National Institutes of Health, National Cancer Institute through the grant U24 CA180918 (PIs Kikinis & Fedorov) and U01 CA151261 (PI Fennessy).")
set(EXTENSION_ICONURL "http://wiki.slicer.org/slicerWiki/images/5/59/MpReviewLogo.png")
set(EXTENSION_SCREENSHOTURLS "http://wiki.slicer.org/slicerWiki/images/d/d1/MpReview-Prostate.gif")


#-----------------------------------------------------------------------------
find_package(Slicer REQUIRED)
include(${Slicer_USE_FILE})

#-----------------------------------------------------------------------------
set(MODULE_NAME mpReview)

#-----------------------------------------------------------------------------
set(MODULE_PYTHON_SCRIPTS
  Util/__init__.py
  Util/mixins.py
  ${MODULE_NAME}.py
  )

set(MODULE_PYTHON_RESOURCES
  Resources/Colors/mpReviewColors.csv
  Resources/Icons/icon-completion_fit.png
  Resources/Icons/icon-infoBox.png
  Resources/Icons/icon-segmentation_fit.png
  Resources/Icons/icon-seriesselection_fit.png
  Resources/Icons/icon-studyselection_fit.png
  Resources/Icons/mpReview-simple-small.png
  Resources/Icons/mpReviewExtensionLogo.png
  Resources/Icons/mpReviewLogo128px.png
  )

#-----------------------------------------------------------------------------
slicerMacroBuildScriptedModule(
  NAME ${MODULE_NAME}
  SCRIPTS ${MODULE_PYTHON_SCRIPTS} 
  RESOURCES ${MODULE_PYTHON_RESOURCES}
  WITH_GENERIC_TESTS
  )

slicerMacroBuildScriptedModule(
  NAME mpReviewPreprocessor
  SCRIPTS mpReviewPreprocessor.py
  RESOURCES ""
  WITH_GENERIC_TESTS
  )

#-----------------------------------------------------------------------------
if(BUILD_TESTING)

  # Register the unittest subclass in the main script as a ctest.
  # Note that the test will also be available at runtime.
  slicer_add_python_unittest(SCRIPT mpReview.py)

  # Additional build-time testing
  # Testing is disabled for now due to the lack of a small realistic dataset
  # that can be used to exercise the module functionality
  # add_subdirectory(Testing)
endif()

#-----------------------------------------------------------------------------
include(${Slicer_EXTENSION_CPACK})
