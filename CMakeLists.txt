cmake_minimum_required(VERSION 2.8.7)

#-----------------------------------------------------------------------------
set(EXTENSION_NAME PCampReview)
set(EXTENSION_HOMEPAGE "http://www.slicer.org/slicerWiki/index.php/Documentation/4.2/Extensions/PCampReview")
set(EXTENSION_CATEGORY "Examples")
set(EXTENSION_CONTRIBUTORS "Jean-Christophe Fillion-Robin (Kitware), Steve Pieper (Isomics)")
set(EXTENSION_DESCRIPTION "This is an example of extension bundling a scripted loadable module")
set(EXTENSION_ICONURL "http://viewvc.slicer.org/viewvc.cgi/Slicer4/trunk/Extensions/Testing/PCampReview/Resources/Icons/PCampReview.png?revision=19437&view=co")
set(EXTENSION_SCREENSHOTURLS "http://wiki.slicer.org/slicerWiki/images/e/e2/Slicer-r19441-PCampReview-screenshot.png")


#-----------------------------------------------------------------------------
find_package(Slicer REQUIRED)
include(${Slicer_USE_FILE})

#-----------------------------------------------------------------------------
set(MODULE_NAME PCampReview)

#-----------------------------------------------------------------------------
set(MODULE_PYTHON_SCRIPTS
  ${MODULE_NAME}.py
  )

set(MODULE_PYTHON_RESOURCES
  Resources/Colors/PCampReviewColors.csv
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
  slicer_add_python_unittest(SCRIPT PCampReview.py)

  # Additional build-time testing
  add_subdirectory(Testing)
endif()

#-----------------------------------------------------------------------------
include(${Slicer_EXTENSION_CPACK})
