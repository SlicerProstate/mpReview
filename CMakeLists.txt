cmake_minimum_required(VERSION 3.0.1)

#-----------------------------------------------------------------------------
set(EXTENSION_NAME mpReview)
set(EXTENSION_HOMEPAGE "https://github.com/SlicerProstate/mpReview")
set(EXTENSION_CATEGORY "Informatics")
set(EXTENSION_CONTRIBUTORS "Andrey Fedorov (Brigham and Women's Hospital), Deepa Krishnaswamy (Brigham and Women's Hospital), Andras Lasso (Queen's University), Robin Weiss (University of Chicago), Alireza Mehrtash (Brigham and Women's Hospital), Christian Herz (Brigham and Women's Hospital)")
set(EXTENSION_DESCRIPTION "The Multiparametric Image Review (mpReview) extension facilitates review and annotation (segmentation) of multi-parametric imaging datasets.

The driving use case for the development of this module was review and segmentation of the regions of interest in prostate cancer multiparametric MRI. 

This work is done as part of the Quantitative Imaging Network (QIN) and Informatics Technology for Cancer Research (ITCR) initiatives of the National Cancer Institute, and is funded by the National Institutes of Health, National Cancer Institute through the grant U24 CA180918 (PIs Kikinis & Fedorov) and U01 CA151261 (PI Fennessy).")

set(EXTENSION_ICONURL "https://raw.githubusercontent.com/SlicerProstate/mpReview/master/Resources/Icons/mpReview.png")
set(EXTENSION_SCREENSHOTURLS "https://raw.githubusercontent.com/SlicerProstate/mpReview/master/Resources/Icons/mpReview_screenshot.PNG")
set(EXTENSION_DEPENDS "SlicerDevelopmentToolbox" "QuantitativeReporting" "DICOMwebBrowser")


#-----------------------------------------------------------------------------
find_package(Slicer REQUIRED)
include(${Slicer_USE_FILE})

#-----------------------------------------------------------------------------
set(MODULE_NAME mpReview)

#-----------------------------------------------------------------------------
set(MODULE_PYTHON_SCRIPTS
  ${MODULE_NAME}.py
  )

file(GLOB_RECURSE MODULE_PYTHON_RESOURCES RELATIVE ${CMAKE_CURRENT_SOURCE_DIR}
  ${PROJECT_SOURCE_DIR}/Resources/*
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

include(${Slicer_EXTENSION_GENERATE_CONFIG})
include(${Slicer_EXTENSION_CPACK})
