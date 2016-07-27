### Intro

Multiparametric Review (mpReview) is a 3D Slicer (see http://slicer.org) module that facilitates review and annotation (segmentation) of multi-parametric imaging datasets. 

This module is work in progress, and has not yet been released as a 3D Slicer extension, but this is in the plans. Development of this module was supported by NIH via grants U01CA151261 and U24CA180918. Contact is Andrey Fedorov, fedorov@bwh.harvard.edu.

### Functionality

The module guides the user through a workflow that consists of the following steps:

1. Select location of input data: the data is expected to be in a certain layout that is described below.
2. Select the study that will be annotated. The list of studies will be determined from the directory layout in the source directory.
3. Select the series that will be used during annotation. The module has some hard-coded logic about what series should be loaded. The user can adjust the selection as needed.
4. Segment one or more series. Upon entering this step, the series selected in the previous step will be loaded. In this step, the user is required to choose the reference series. Once selected, the reference series will be selected as the Background layer (using Slicer terminology) in all slice viewers. The slice viewer layout will be initialized automatically to show all the series, with the non-reference series in the Foreground layer. At this time, the user can use embedded Editor module to prepare segmentation labels of the reference series.

Once annotation task is completed, the result can be saved in the directory hierarchy.

The workflow can be linked with a Google form to support subject-specific form-based review, with the subject and reader IDs pre-populated, as illustrated in this module.

WindowLevelExtension
(http://wiki.slicer.org/slicerWiki/index.php/Documentation/Nightly/Extensions/WindowLevelEffect)
can be used to simplify setting window/level for the Foreground volume in 3D
Slicer.

### Dependencies

This module expects that WindowLevelEffect extension (http://wiki.slicer.org/slicerWiki/index.php/Documentation/Nightly/Extensions/WindowLevelEffect) is installed. It is available from Slicer Extensions Manager.

### Data organization conventions

The module expects that data is arranged in uniquely-named folders, each of which corresponds to an imaging study (in the DICOM meaning of a study). The data layout (see below, as printed by the Linux tree command line tool) somewhat mimics the layout used internally by XNAT (since this is what the author used internally for data organization). Each study is expected to have one top-level folder called RESOURCES. Within that folder, it is expected to have one folder for each imaging series, with the folder name matching the series number. Each series should have a sub-folder called Reconstructions. Reconstructions folder should contain:

1. Image volume in NRRD format (see http://teem.sourceforge.net/nrrd/index.html), or any volumetric format recognized by 3D Slicer. 
2. .xml file containing the output of DCMTK dcm2xml utility (see
   http://support.dcmtk.org/docs/dcm2xml.html).

A converter utility is provided in Util/mpReviewPreprocessor.py to put a
collection of DICOM files into the format and hierarchy expected by
mpReview. Here is how converter should be used:

```
Slicer --no-main-window --no-splash --python-script \
Util/mpReviewPreprocessor.py -i <input folder, can contain sub-folders> -o <output folder>
```

And this is an example of the data layout for one imaging study after applying the converter.

```
└── RESOURCES
    ├── 1
    │   └── Reconstructions
    │       ├── 1.nrrd
    │       └── 1.xml
    ├── 100
    │   ├── Reconstructions
    │   │   ├── 100.nrrd
    │   │   └── 100.xml
    │   └── Segmentations
    │       └── readerId-20140206103922.nrrd
    ├── 2
    │   └── Reconstructions
    │       ├── 2.nrrd
    │       └── 2.xml
    ├── 5
    │   ├── Reconstructions
    │   │   ├── 5.nrrd
    │   │   └── 5.xml
    │   └── Segmentations
    │       └── readerId-20140206103922.nrrd
    ├── 6
    │   └── Reconstructions
    │       ├── 6.nrrd
    │       └── 6.xml
    ├── 7
    │   └── Reconstructions
    │       ├── 7.nrrd
    │       └── 7.xml
    ├── 700
    │   └── Reconstructions
    │       ├── 700.nrrd
    │       └── 700.xml
    ├── 701
    │   ├── Reconstructions
    │   │   ├── 701.nrrd
    │   │   └── 701.xml
    │   └── Segmentations
    │       └── readerId-20140206103922.nrrd
    ├── 8
    │   └── Reconstructions
    │       ├── 8.nrrd
    │       └── 8.xml
    ├── 800
    │   └── Reconstructions
    │       ├── 800.nrrd
    │       └── 800.xml
    └── 801
        ├── Reconstructions
        │   ├── 801.nrrd
        │   └── 801.xml
        └── Segmentations
            └── readerId-20140206103922.nrrd
``` 

TODO: update the above to follow the current organization and naming
conventions!

The list of labels used for segmentations is available as a spreadsheet here: 
http://goo.gl/7Rtgqp

## Acknowledgments

This work supported in part the National Institutes of Health, National Cancer Institute through the following grants:
* Quantitative MRI of prostate cancer as a biomarker and guide for treatment, Quantitative Imaging Network (U01 CA151261, PI Fennessy)
* Enabling technologies for MRI-guided prostate interventions (R01 CA111288, PI Tempany)
* The National Center for Image-Guided Therapy (P41 EB015898, PI Tempany)
* Quantitative Image Informatics for Cancer Research (QIICR) (U24 CA180918, PIs Kikinis and Fedorov)

The following individuals and groups contributed directly to the development of SlicerProstate functionality:
* Andrey Fedorov, Brigham and Women's Hospital
* Alireza Mehrtash, Brigham and Women's Hospital
* Robin Weiss, University of Chicago
* Christian Herz, Brigham and Women's Hospital
