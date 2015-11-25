import logging, qt, ctk, os, slicer


class ModuleWidgetMixin(object):

  @property
  def layoutManager(self):
    return slicer.app.layoutManager()

  @property
  def dicomDatabase(self):
    return slicer.dicomDatabase

  @staticmethod
  def makeProgressIndicator(maxVal=100, initialValue=0):
    progressIndicator = qt.QProgressDialog()
    progressIndicator.minimumDuration = 0
    progressIndicator.modal = True
    progressIndicator.setMaximum(maxVal)
    progressIndicator.setValue(initialValue)
    progressIndicator.setWindowTitle("Processing...")
    progressIndicator.show()
    progressIndicator.autoClose = False
    return progressIndicator

  @staticmethod
  def confirmOrSaveDialog(message, title='mpReview'):
    box = qt.QMessageBox(qt.QMessageBox.Question, title, message)
    box.addButton("Exit, discard changes", qt.QMessageBox.AcceptRole)
    box.addButton("Save changes", qt.QMessageBox.ActionRole)
    box.addButton("Cancel", qt.QMessageBox.RejectRole)
    return box.exec_()

  @staticmethod
  def confirmDialog(message, title='mpReview'):
    result = qt.QMessageBox.question(slicer.util.mainWindow(), title, message,
                                     qt.QMessageBox.Ok | qt.QMessageBox.Cancel)
    return result == qt.QMessageBox.Ok

  @staticmethod
  def notificationDialog(message, title='mpReview'):
    return qt.QMessageBox.information(slicer.util.mainWindow(), title, message)

  @staticmethod
  def yesNoDialog(message, title='mpReview'):
    result = qt.QMessageBox.question(slicer.util.mainWindow(), title, message,
                                     qt.QMessageBox.Yes | qt.QMessageBox.No)
    return result == qt.QMessageBox.Yes

  @staticmethod
  def warningDialog(message, title='mpReview'):
    return qt.QMessageBox.warning(slicer.util.mainWindow(), title, message)

  def getSetting(self, setting):
    settings = qt.QSettings()
    return str(settings.value(self.moduleName + '/' + setting))

  def setSetting(self, setting, value):
    settings = qt.QSettings()
    settings.setValue(self.moduleName + '/' + setting, value)

  def createHLayout(self, elements, **kwargs):
    return self._createLayout(qt.QHBoxLayout, elements, **kwargs)

  def createVLayout(self, elements, **kwargs):
    return self._createLayout(qt.QVBoxLayout, elements, **kwargs)

  def _createLayout(self, layoutClass, elements, **kwargs):
    widget = qt.QWidget()
    rowLayout = layoutClass()
    widget.setLayout(rowLayout)
    for element in elements:
      rowLayout.addWidget(element)
    for key, value in kwargs.iteritems():
      if hasattr(rowLayout, key):
        setattr(rowLayout, key, value)
    return widget

  def _createListView(self, name, headerLabels):
    view = qt.QListView()
    view.setObjectName(name)
    view.setSpacing(3)
    model = qt.QStandardItemModel()
    model.setHorizontalHeaderLabels(headerLabels)
    view.setModel(model)
    view.setEditTriggers(qt.QAbstractItemView.NoEditTriggers)
    return view, model

  def createIcon(self, filename, iconPath=None):
    if not iconPath:
      iconPath = os.path.join(self.modulePath, 'Resources/Icons')
    path = os.path.join(iconPath, filename)
    pixmap = qt.QPixmap(path)
    return qt.QIcon(pixmap)

  def createSliderWidget(self, minimum, maximum):
    slider = slicer.qMRMLSliderWidget()
    slider.minimum = minimum
    slider.maximum = maximum
    return slider

  def createLabel(self, title, **kwargs):
    label = qt.QLabel(title)
    return self.extendQtGuiElementProperties(label, **kwargs)

  def createButton(self, title, **kwargs):
    button = qt.QPushButton(title)
    button.setCursor(qt.Qt.PointingHandCursor)
    return self.extendQtGuiElementProperties(button, **kwargs)

  def createRadioButton(self, text, **kwargs):
    button = qt.QRadioButton(text)
    button.setCursor(qt.Qt.PointingHandCursor)
    return self.extendQtGuiElementProperties(button, **kwargs)

  def createDirectoryButton(self, **kwargs):
    button = ctk.ctkDirectoryButton()
    for key, value in kwargs.iteritems():
      if hasattr(button, key):
        setattr(button, key, value)
    return button

  def extendQtGuiElementProperties(self, element, **kwargs):
    for key, value in kwargs.iteritems():
      if hasattr(element, key):
        setattr(element, key, value)
      else:
        if key == "fixedHeight":
          element.minimumHeight = value
          element.maximumHeight = value
        elif key == 'hidden':
          if value:
            element.hide()
          else:
            element.show()
        else:
          logging.error("%s does not have attribute %s" % (element.className(), key))
    return element

  def createComboBox(self, **kwargs):
    combobox = slicer.qMRMLNodeComboBox()
    combobox.addEnabled = False
    combobox.removeEnabled = False
    combobox.noneEnabled = True
    combobox.showHidden = False
    for key, value in kwargs.iteritems():
      if hasattr(combobox, key):
        setattr(combobox, key, value)
      else:
        logging.error("qMRMLNodeComboBox does not have attribute %s" % key)
    combobox.setMRMLScene(slicer.mrmlScene)
    return combobox