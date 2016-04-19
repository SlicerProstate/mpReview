import SimpleITK as sitk
import sys

i=sitk.ReadImage(sys.argv[1])
s=sitk.LabelStatisticsImageFilter()
s.Execute(i,i)
labels = s.GetLabels()
if len(labels)!=1:
  print "No:",sys.argv[1]
