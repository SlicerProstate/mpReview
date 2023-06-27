### Intro

Multiparametric Review (mpReview) is a 3D Slicer (see http://slicer.org) module that facilitates review and annotation (segmentation) of multi-parametric imaging datasets. 

Development of this module was supported by NIH via grants U01CA151261, U24CA180918 and T32EB025823-04. Contact is Andrey Fedorov, fedorov@bwh.harvard.edu and Deepa Krishnaswamy, dkrishnaswamy@bwh.harvard.edu. 


### Functionality

The module guides the user through a workflow that consists of the following steps:

1. Select location of input data. The module works specifically with DICOM data. There are three options to input data to the module.
   1. Data can be loaded from the local Slicer DICOM database.
   2. Data can be loaded from Google Cloud Platform, where the data is stored in a DICOM datastore. See Setup below for additional details on how to authenticate. 
   3. Data can be loaded from any other remote server, e.g. Kaapana. 
2. Select the study that will be annotated. The list of studies will be populated from the input local or remote database.
3. Select the series that will be used during annotation. The module has some hard-coded logic about what series should be loaded.  Currently, the user can only select MR/CT/PET series. Series that are not checkable but still shown in the list include DICOM Segmentation (SEG) objects and Structured Reports (SR). The latest SEG will be automatically loaded in a later step. 
4. Segment one or more series. Upon entering this step, the series selected in the previous step will be loaded. In this step, the user is required to choose the reference series. Once selected, the reference series will be selected as the Background layer (using Slicer terminology) in all slice viewers. The slice viewer layout will be initialized automatically to show all the series, with the non-reference series in the Foreground layer. At this time, the user can use embedded segment editor to prepare segmentation labels of the reference series. The user can define segments according to the terminology file loaded, see Additional Notes below. 
5. Save the data. A DICOM SEG object will be saved first to the local Slicer DICOM database, and uploaded to the remote server if chosen. 

### Setup 

1. Install the following extensions: QuantitativeReporting and SlicerDICOMWeb. The rest of the extensions needed will be installed automatically when installing QuantitativeReporting.
2. If using Google Cloud Platform, you will need to install the [Google SDK](https://cloud.google.com/sdk). To authenticate, run `gcloud auth login`. For windows useres, Google SDK will be automatically found when starting Slicer. For Mac users, you will need to activate the environment you installed Google SDK in, authenticate, and then start Slicer from command line. 

### Additional Notes

1. Currently, a terminology file for prostate cancer and anatomy is used. This could be replaced by a terminology file appropriate for the user's segmentation task.
2. When the user loads in a series at a later timepoint to continue segmentation, the latest DICOM SEG object will be automatically loaded. A new DICOM SEG object will be saved each time. 

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
