from __main__ import vtk, qt, ctk, slicer
import PCampReviewLib

class LesionFormParameterNode:
  def __init__(self):
    self.x = []
    self.y = []
    self.T2score = -1
    self.DWIscore = -1
    self.DCEscore = -1
    self.lesionName = ''

class LesionFormWidget(PCampReviewLib.pqWidget):
  """
  Widget that manages the PI-RADS review form for a lesion.
  This widget initializes the form based on the content of the
  parameter node (scores and contrast uptake plot), and responds
  to user updates of the scores to update the parameter node.

  Input:
    param.x/param.y - array of x and y values for curve plotting
    param.T2score - T2 assigned score (1-5)
    param.DWIscore - DWI assigned score (1-5)
    param.DCEscore - DCE assigned score (1-5)

  """

  def __init__(self,param):
    super(LesionFormWidget,self).__init__()

    # parameters node keeps all that is needed to render
    # the form and to store the scores
    self.param = param

    self.widget = qt.QWidget()
    self.layout = qt.QHBoxLayout(self.widget)

    lesionNameWidget = qt.QWidget()
    scoreSheetWidget = qt.QWidget()
    plotWidget = qt.QWidget()

    lnLayout = qt.QVBoxLayout(lesionNameWidget)
    ssLayout = qt.QVBoxLayout(scoreSheetWidget)
    pLayout = qt.QVBoxLayout(plotWidget)

    lesionName = qt.QLabel(self.param.lesionName)
    lnLayout.addWidget(lesionName)

    w = qt.QWidget()
    wl = qt.QHBoxLayout(w)

    for i in range(0,6):
      if i:
        label = qt.QLabel(str(i))
      else:
        label = qt.QLabel('')

      wl.addWidget(label)

    ssLayout.addWidget(w)

    w = qt.QWidget()
    wl = qt.QHBoxLayout(w)

    t2label = qt.QLabel('T2W')
    wl.addWidget(t2label)
    t2radios = []
    self.t2group = qt.QButtonGroup()
    for i in range(1,6):
      t2radios.append(qt.QRadioButton())
      self.t2group.addButton(t2radios[-1],i)
      wl.addWidget(t2radios[-1])
    self.t2group.connect('buttonClicked(int)', self.onT2scoreUpdated)
  
    ssLayout.addWidget(w)
  
    w = qt.QWidget()
    wl = qt.QHBoxLayout(w)
  
    dwilabel = qt.QLabel('DWI')
    wl.addWidget(dwilabel)
    dwiradios = []
    self.dwigroup = qt.QButtonGroup()
    for i in range(1,6):
      dwiradios.append(qt.QRadioButton())
      self.dwigroup.addButton(dwiradios[-1],i)
      wl.addWidget(dwiradios[-1])
    self.dwigroup.connect('buttonClicked(int)', self.onDWIscoreUpdated)
  
    ssLayout.addWidget(w)
  
    w = qt.QWidget()
    wl = qt.QHBoxLayout(w)
  
    dcelabel = qt.QLabel('DCE')
    wl.addWidget(dcelabel)
    dceradios = []
    self.dcegroup = qt.QButtonGroup()
    for i in range(1,6):
      dceradios.append(qt.QRadioButton())
      self.dcegroup.addButton(dceradios[-1],i)
      wl.addWidget(dceradios[-1])
    self.dcegroup.connect('buttonClicked(int)', self.onDCEscoreUpdated)
  
    ssLayout.addWidget(w)
  
    chartView = ctk.ctkVTKChartView(plotWidget)
    chart = chartView.chart()
    table = vtk.vtkTable()
    x = vtk.vtkFloatArray()
    y = vtk.vtkFloatArray()
    x.SetName('time point')
    y.SetName('signal intensity')
    table.AddColumn(x)
    table.AddColumn(y)
  
    table.SetNumberOfRows(100)
    for c in range(len(self.param.x)):
      table.SetValue(c,0,self.param.x[c])
      table.SetValue(c,1,self.param.y[c])
    
    plot = chart.AddPlot(0)
    plot.SetInput(table,0,1)
    chart.AddPlot(0)
  
    cw = qt.QWidget()
    cwl = qt.QVBoxLayout(cw)
    cwl.addWidget(chartView)
    pLayout.addWidget(cw)

    self.layout.addWidget(lesionNameWidget)
    self.layout.addWidget(scoreSheetWidget)
    self.layout.addWidget(plotWidget)
  
  def onT2scoreUpdated(self,score):
    self.param.T2score = score
  
  def onDWIscoreUpdated(self,score):
    self.param.DWIscore = score

  def onDCEscoreUpdated(self,score):
    self.param.DCEscore = score

  def getParameterNode(self):
    return self.param
