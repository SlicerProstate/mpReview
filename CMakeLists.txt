cmake_minimum_required(VERSION 2.8.7)

#-----------------------------------------------------------------------------
set(EXTENSION_NAME mpReview)
set(EXTENSION_HOMEPAGE "http://www.slicer.org/slicerWiki/index.php/Documentation/4.2/Extensions/mpReview")
set(EXTENSION_CATEGORY "Examples")
set(EXTENSION_CONTRIBUTORS "Jean-Christophe Fillion-Robin (Kitware), Steve Pieper (Isomics)")
set(EXTENSION_DESCRIPTION "This is an example of extension bundling a scripted loadable module")
set(EXTENSION_ICONURL "http://viewvc.slicer.org/viewvc.cgi/Slicer4/trunk/Extensions/Testing/mpReview/Resources/Icons/mpReview.png?revision=19437&view=co")
set(EXTENSION_SCREENSHOTURLS "http://wiki.slicer.org/slicerWiki/images/e/e2/Slicer-r19441-mpReview-screenshot.png")


#-----------------------------------------------------------------------------
find_package(Slicer REQUIRED)
include(${Slicer_USE_FILE})

#-----------------------------------------------------------------------------
set(MODULE_NAME mpReview)

#-----------------------------------------------------------------------------
set(MODULE_PYTHON_SCRIPTS
  ${MODULE_NAME}.py
  )

set(MODULE_PYTHON_RESOURCES
  Resources/Colors/mpReviewColors.csv
  )

#-----------------------------------------------------------------------------
slicerMacroBuildScriptedModule(
  NAME ${MODULE_NAME}
  SCRIPTS ${MODULE_PYTHON_SCRIPTS} 
  RESOURCES ${MODULE_PYTHON_RESOURCES}
  WITH_GENERIC_TESTS
  )

#-----------------------------------------------------------------------------
if(BUILD_TESTING)

  # Register the unittest subclass in the main script as a ctest.
  # Note that the test will also be available at runtime.
  slicer_add_python_unittest(SCRIPT mpReview.py)

  # Additional build-time testing
  add_subdirectory(Testing)
  add_subdirectory(mpReviewPreprocessorSelfTest)
  add_subdirectory(mpReviewSelfTest)
endif()

#-----------------------------------------------------------------------------
include(${Slicer_EXTENSION_CPACK})
