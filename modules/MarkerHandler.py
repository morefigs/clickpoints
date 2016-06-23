from __future__ import division, print_function
import os
import re
import peewee


from qtpy import QtGui, QtCore, QtWidgets
from qtpy.QtCore import Qt
import qtawesome as qta

import numpy as np
from sortedcontainers import SortedDict

from qimage2ndarray import array2qimage, rgb_view

import uuid

import json
import matplotlib.pyplot as plt
import random

from QtShortCuts import AddQSpinBox, AddQLineEdit, AddQLabel, AddQComboBox, AddQColorChoose, GetColorByIndex
from Tools import GraphicsItemEventFilter, disk, PosToArray, BroadCastEvent, HTMLColorToRGB

w = 1.
b = 7
r2 = 10
path1 = QtGui.QPainterPath()
path1.addRect(-r2, -w, b, w * 2)
path1.addRect(r2, -w, -b, w * 2)
path1.addRect(-w, -r2, w * 2, b)
path1.addRect(-w, r2, w * 2, -b)
path1.addEllipse(-r2, -r2, r2 * 2, r2 * 2)
path1.addEllipse(-r2, -r2, r2 * 2, r2 * 2)
w = 2
b = 3
o = 3
path2 = QtGui.QPainterPath()
path2.addRect(-b - o, -w * 0.5, b, w)
path2.addRect(+o, -w * 0.5, b, w)
path2.addRect(-w * 0.5, -b - o, w, b)
path2.addRect(-w * 0.5, +o, w, b)
r3 = 5
path3 = QtGui.QPainterPath()
path3.addEllipse(-0.5 * r3, -0.5 * r3, r3, r3)  # addRect(-0.5,-0.5, 1, 1)
point_display_types = [path1, path2, path3]
point_display_type = 0

path_circle = QtGui.QPainterPath()
#path_circle.arcTo(-5, -5, 10, 10, 0, 130)
path_circle.addEllipse(-5, -5, 10, 10)

paths = dict(cross=path1, circle=path_circle)

TYPE_Normal = 0
TYPE_Rect = 1
TYPE_Line = 2
TYPE_Track = 4

class MarkerFile:
    def __init__(self, datafile):
        self.data_file = datafile

        self.table_markertype = self.data_file.table_markertype
        self.table_marker = self.data_file.table_marker
        self.table_track = self.data_file.table_track

    def set_track(self, type):
        track = self.table_track(uid=uuid.uuid4().hex, type=type)
        track.save()
        return track

    def set_type(self, id, name, rgb_tuple, mode):
        try:
            type = self.table_markertype.get(self.table_markertype.name == name)
        except peewee.DoesNotExist:
            type = self.table_markertype(name=name, color='#%02x%02x%02x' % tuple(rgb_tuple), mode=mode)
            type.save(force_insert=True)
        return type

    def add_marker(self, **kwargs):
        kwargs.update(dict(image=self.data_file.image))
        return self.table_marker(**kwargs)

    def get_marker_list(self, image_id=None):
        if image_id is None:
            image_id = self.data_file.image.id
        return self.table_marker.select().where(self.table_marker.image == image_id)

    def get_type_list(self):
        return self.table_markertype.select()

    def get_type(self, name):
        return self.table_markertype.get(name=name)

    def get_track_list(self):
        return self.table_track.select()

    def get_track_points(self, track):
        return self.table_marker.select().where(self.table_marker.track == track)

    def get_marker_frames(self):
        return self.table_marker.select().group_by(self.table_marker.image)


def ReadTypeDict(string):
    dictionary = {}
    matches = re.findall(
        r"(\d*):\s*\[\s*\'([^']*?)\',\s*\[\s*([\d.]*)\s*,\s*([\d.]*)\s*,\s*([\d.]*)\s*\]\s*,\s*([\d.]*)\s*\]", string)
    for match in matches:
        dictionary[int(match[0])] = [match[1], map(float, match[2:5]), int(match[5])]
    return dictionary


def GetColorFromMap(identifier, id):
    match = re.match(r"([^\(]*)\((\d*)\)", identifier)
    count = 100
    if match:
        result = match.groups()
        identifier = result[0]
        count = int(result[1])
    cmap = plt.get_cmap(identifier)
    if id is None:
        id = 0
    index = int((id*255/count) % 256)
    color = np.array(cmap(index))
    color = color[:3]*255
    return color


class DeleteType(QtWidgets.QDialog):
    def __init__(self, type, count, types):
        QtWidgets.QDialog.__init__(self)

        # Widget
        self.setMinimumWidth(500)
        self.setMinimumHeight(100)
        self.setWindowTitle("Delete Type")
        self.setWindowIcon(qta.icon("fa.crosshairs"))
        self.setModal(True)
        main_layout = QtWidgets.QVBoxLayout(self)

        self.label = QtWidgets.QLabel("The type %s has %d marker. Do you want to delete all of them or assign them to another type?" % (type.name, count))
        main_layout.addWidget(self.label)

        self.type_ids = {type.name: type.id for type in types}
        self.comboBox = AddQComboBox(main_layout, "New Type:", [type.name for type in types])

        layout2 = QtWidgets.QHBoxLayout()
        main_layout.addLayout(layout2)
        button1 = QtWidgets.QPushButton("Delete")
        button1.clicked.connect(lambda: self.done(-1))
        layout2.addWidget(button1)
        button2 = QtWidgets.QPushButton("Move")
        button2.clicked.connect(lambda: self.done(self.type_ids[self.comboBox.currentText()]))
        layout2.addWidget(button2)
        button3 = QtWidgets.QPushButton("Cancel")
        button3.clicked.connect(lambda: self.done(0))
        layout2.addWidget(button3)


class MarkerEditor(QtWidgets.QWidget):
    data = None

    def __init__(self, marker_handler, data_file):
        QtWidgets.QWidget.__init__(self)

        self.data_file = data_file

        # Widget
        self.setMinimumWidth(500)
        self.setMinimumHeight(200)
        self.setWindowTitle("MarkerEditor - ClickPoints")
        self.setWindowIcon(qta.icon("fa.crosshairs"))
        main_layout = QtWidgets.QHBoxLayout(self)

        self.marker_handler = marker_handler
        self.db = marker_handler.marker_file

        """ Tree View """
        tree = QtWidgets.QTreeView()
        main_layout.addWidget(tree)

        self.marker_modelitems = {}
        self.modelItems_marker = {}

        model = QtGui.QStandardItemModel(0, 0)
        types = self.db.table_markertype.select()
        for row, type in enumerate(types):
            item = QtGui.QStandardItem(type.name)
            item.setIcon(qta.icon("fa.crosshairs", color=QtGui.QColor(*HTMLColorToRGB(type.color))))
            item.setEditable(False)
            item.entry = type

            if type.mode & TYPE_Track:
                tracks = self.db.table_track.select().where(self.db.table_track.type == type)
                for track in tracks:
                    child = QtGui.QStandardItem("Track #%d" % track.id)
                    child.entry = track
                    child.setEditable(False)
                    item.appendRow(child)
                    markers = self.db.table_marker.select().where(self.db.table_marker.track == track)\
                              .join(self.db.data_file.table_image).order_by(self.db.data_file.table_image.sort_index)
                    count = 0
                    for marker in markers:
                        child2 = QtGui.QStandardItem("Marker #%d (frame %d)" % (marker.id, marker.image.sort_index))
                        child2.setEditable(False)
                        child.appendRow(child2)
                        self.marker_modelitems[marker.id] = child2
                        child2.entry = marker
                        count += 1
                    child.setText("Track #%d (%d)" % (track.id, count))
            else:
                markers = self.db.table_marker.select().where(self.db.table_marker.type == type)
                for marker in markers:
                    child = QtGui.QStandardItem("Marker #%d (frame %d)" % (marker.id, marker.image.sort_index))
                    child.setEditable(False)
                    item.appendRow(child)
                    self.marker_modelitems[marker.id] = child
                    child.entry = marker

            model.setItem(row, 0, item)
        item = QtGui.QStandardItem("add type")
        item.setIcon(qta.icon("fa.plus"))
        item.setEditable(False)
        self.new_type = self.db.table_markertype()
        self.new_type.color = GetColorByIndex(types.count())
        item.entry = self.new_type
        model.setItem(row+1, 0, item)

        tree.setUniformRowHeights(True)
        tree.setHeaderHidden(True)
        tree.setAnimated(True)
        tree.setModel(model)
        tree.clicked.connect(lambda index: self.setMarker(index.model().itemFromIndex(index).entry))
        tree.selectionModel().selectionChanged.connect(lambda selection, y: self.setMarker(selection.indexes()[0].model().itemFromIndex(selection.indexes()[0]).entry))
        self.tree = tree

        self.layout = QtWidgets.QVBoxLayout()
        main_layout.addLayout(self.layout)

        self.StackedWidget = QtWidgets.QStackedWidget(self)
        self.layout.addWidget(self.StackedWidget)

        """ Marker Properties """
        self.markerWidget = QtWidgets.QGroupBox()
        self.StackedWidget.addWidget(self.markerWidget)
        layout = QtWidgets.QVBoxLayout(self.markerWidget)
        self.markerWidget.type_indices = {t.id: index for index, t in enumerate(self.db.get_type_list())}
        self.markerWidget.type = AddQComboBox(layout, "Type:", [t.name for t in self.db.get_type_list()])
        self.markerWidget.x = AddQSpinBox(layout, "X:")
        self.markerWidget.y = AddQSpinBox(layout, "Y:")
        self.markerWidget.style = AddQLineEdit(layout, "Style:")
        self.markerWidget.text = AddQLineEdit(layout, "Text:")
        self.markerWidget.label = AddQLabel(layout)
        layout.addStretch()

        """ Type Properties """
        self.typeWidget = QtWidgets.QGroupBox()
        self.StackedWidget.addWidget(self.typeWidget)
        layout = QtWidgets.QVBoxLayout(self.typeWidget)
        self.typeWidget.name = AddQLineEdit(layout, "Name:")
        self.typeWidget.mode_indices = {TYPE_Normal: 0, TYPE_Line: 1, TYPE_Rect: 2,TYPE_Track: 3}
        self.typeWidget.mode_values = {0: TYPE_Normal, 1: TYPE_Line, 2: TYPE_Rect, 3: TYPE_Track}
        self.typeWidget.mode = AddQComboBox(layout, "Mode:", ["TYPE_Normal", "TYPE_Line", "TYPE_Rect", "TYPE_Track"])
        self.typeWidget.style = AddQLineEdit(layout, "Style:")
        self.typeWidget.color = AddQColorChoose(layout, "Color:")
        self.typeWidget.text = AddQLineEdit(layout, "Text:")
        layout.addStretch()

        """ Track Properties """
        self.trackWidget = QtWidgets.QGroupBox()
        self.StackedWidget.addWidget(self.trackWidget)
        layout = QtWidgets.QVBoxLayout(self.trackWidget)
        self.trackWidget.style = AddQLineEdit(layout, "Style:")
        self.trackWidget.text = AddQLineEdit(layout, "Text:")
        layout.addStretch()

        """ Control Buttons """
        horizontal_layout = QtWidgets.QHBoxLayout()
        self.layout.addLayout(horizontal_layout)
        self.pushbutton_Confirm = QtWidgets.QPushButton('S&ave', self)
        self.pushbutton_Confirm.pressed.connect(self.saveMarker)
        horizontal_layout.addWidget(self.pushbutton_Confirm)

        self.pushbutton_Remove = QtWidgets.QPushButton('R&emove', self)
        self.pushbutton_Remove.pressed.connect(self.removeMarker)
        horizontal_layout.addWidget(self.pushbutton_Remove)

        self.pushbutton_Cancel = QtWidgets.QPushButton('&Cancel', self)
        self.pushbutton_Cancel.pressed.connect(self.close)
        horizontal_layout.addWidget(self.pushbutton_Cancel)

    def setMarker(self, data, data_type=None):
        if type(data) == self.db.table_marker and self.data == data:
            self.marker_handler.window.JumpToFrame(self.data.image.sort_index)
        self.data = data

        self.pushbutton_Remove.setHidden(False)

        if type(data) == self.db.table_marker:
            self.StackedWidget.setCurrentIndex(0)
            self.markerWidget.setTitle("Marker #%d" % data.id)

            self.tree.setCurrentIndex(self.marker_modelitems[data.id].index())

            data2 = data.partner if data.partner_id is not None else None

            text = ''

            if data.type.mode & TYPE_Line:
                if data2 is not None:
                    text += 'Line Length %.2f' % np.linalg.norm(np.array([data.x, data.y])-np.array([data2.x, data2.y]))
                else:
                    text += 'Line not connected'
            elif data.type.mode & TYPE_Rect:
                if data2 is not None:
                    text += 'Rect width %.2f height %.2f' % (abs(data.x-data2.x), abs(data.y-data2.y))
                else:
                    text += 'Rect not connected'
            else:
                text += ''

            self.markerWidget.label.setText(text)

            self.markerWidget.type.setCurrentIndex(self.markerWidget.type_indices[data.type.id])
            self.markerWidget.x.setValue(data.x)
            self.markerWidget.y.setValue(data.y)
            self.markerWidget.style.setText(data.style if data.style else "")
            self.markerWidget.text.setText(data.text if data.text else "")

        elif type(data) == self.db.table_track:
            self.StackedWidget.setCurrentIndex(2)
            self.trackWidget.setTitle("Track #%d" % data.id)
            self.trackWidget.style.setText(data.style if data.style else "")
            self.trackWidget.text.setText(data.text if data.text else "")

        elif type(data) == self.db.table_markertype or data_type == "type":
            if data is None:
                data = self.new_type
                self.data = data
            self.StackedWidget.setCurrentIndex(1)
            if data.name is None:
                self.pushbutton_Remove.setHidden(True)
            self.typeWidget.setTitle("Type #%s" % data.name)
            self.typeWidget.name.setText(data.name)
            try:
                self.typeWidget.mode.setCurrentIndex(self.typeWidget.mode_indices[data.mode])
            except KeyError:
                pass
            self.typeWidget.style.setText(data.style if data.style else "")
            self.typeWidget.color.setColor(data.color)
            self.typeWidget.text.setText(data.text if data.text else "")

    def filterText(self, input):
        # if text field is empty - add Null instead of "" to sql db
        if not input:
            return None
        return input

    def saveMarker(self):
        print("Saving changes...")
        # set parameters
        if type(self.data) == self.db.table_marker:
            self.data.x = self.markerWidget.x.value()
            self.data.y = self.markerWidget.y.value()
            self.data.type = self.marker_handler.marker_file.get_type(self.markerWidget.type.currentText())
            self.data.style = self.markerWidget.style.text()
            self.data.text = self.filterText(self.markerWidget.text.text())
            self.data.save()

            # load updated data
            if self.data.track:
                track_item = self.marker_handler.GetTrackItem(self.data.track)
                track_item.update(self.data.image.sort_index, self.data)
            else:
                marker_item = self.marker_handler.GetMarkerItem(self.data)
                if marker_item:
                    marker_item.ReloadData()
        elif type(self.data) == self.db.table_track:
            self.data.style = self.trackWidget.style.text()
            self.data.text = self.filterText(self.trackWidget.text.text())
            self.data.save()

            self.marker_handler.ReloadTrack(self.data)
        elif type(self.data) == self.db.table_markertype:
            self.data.name = self.typeWidget.name.text()
            self.data.mode = self.typeWidget.mode_values[self.typeWidget.mode.currentIndex()]
            self.data.style = self.typeWidget.style.text()
            self.data.color = self.typeWidget.color.getColor()
            self.data.text = self.filterText(self.typeWidget.text.text())
            self.data.save()
            self.marker_handler.UpdateCounter()
            if self.data.mode & TYPE_Track:
                self.marker_handler.LoadTracks()
            else:
                self.marker_handler.LoadPoints()

        # close widget
        self.marker_handler.marker_edit_window = None
        self.close()

    def removeMarker(self):
        print("Remove ...")
        # currently selected a marker -> remove the marker
        if type(self.data) == self.db.table_marker:
            if self.data.track is None:
                # find point
                marker_item = self.marker_handler.GetMarkerItem(self.data)
                # delete marker
                if marker_item:
                    marker_item.delete()
                else:
                    self.data.delete_instance()
            else:
                # find corresponding track and remove the point
                track_item = self.marker_handler.GetTrackItem(self.data.track)
                track_item.RemoveTrackPoint(self.data.image.sort_index)
                    
        # currently selected a track -> remove the track
        elif type(self.data) == self.db.table_track:
            # get the track and remove it
            track = self.marker_handler.GetTrackItem(self.data)
            track.delete()

        # currently selected a type -> remove the type
        elif type(self.data) == self.db.table_markertype:
            count = self.data.markers.count()
            # if this type doesn't have markers delete it without asking
            if count == 0:
                self.data.delete_instance()
            else:
                # Ask the user if he wants to delete all markers from this type or assign them to a different type
                self.window = DeleteType(self.data, count, [marker_type for marker_type in self.data_file.get_type_list() if marker_type != self.data])
                value = self.window.exec_()
                if value == 0:  # canceled
                    return
                if value == -1:  # delete all of them
                    # delete all markers from this type
                    q = self.data_file.table_marker.delete().where(self.data_file.table_marker.type == self.data.id)
                    q.execute()
                    # delete type
                    self.data.delete_instance()
                    # reload marker
                    self.marker_handler.ReloadMarker()
                else:
                    # change the type of all markers which belonged to this type
                    q = self.data_file.table_marker.select().where(self.data_file.table_marker.type == self.data.id)
                    for marker in q:
                        marker.type = value
                        marker.save()
                    # delete type
                    self.data.delete_instance()
                    # reload marker
                    self.marker_handler.ReloadMarker()

            self.marker_handler.UpdateCounter()

        # close widget
        self.marker_handler.marker_edit_window = None
        self.close()

    def keyPressEvent(self, event):
        if event.key() == QtCore.Qt.Key_Escape:
            self.marker_handler.marker_edit_window = None
            self.close()
        if event.key() == QtCore.Qt.Key_Return:
            self.saveMarker()


class MyMarkerItem(QtWidgets.QGraphicsPathItem):
    style = {}
    scale_value = 1

    dragged = False
    UseCrosshair = True

    partner = None
    rectObj = None

    font = None
    text = None

    def __init__(self, marker_handler, parent, data, saved=False):
        QtWidgets.QGraphicsPathItem.__init__(self, parent)
        self.parent = parent
        self.marker_handler = marker_handler
        self.data = data
        self.config = self.marker_handler.config
        self.saved = saved

        self.GetStyle()

        self.UpdatePath()
        self.setPos(self.data.x, self.data.y)
        self.setZValue(20)

        if len(self.marker_handler.counter):
            self.marker_handler.GetCounter(self.data.type).AddCount(1)

        self.setAcceptHoverEvents(True)

        if self.data.type and (self.data.type.mode & TYPE_Rect or self.data.type.mode & TYPE_Line):
            self.FindPartner()

        if self.partner:
            if self.data.type.mode & TYPE_Rect:
                self.rectObj = QtWidgets.QGraphicsRectItem(self.parent)
            elif self.data.type.mode & TYPE_Line:
                self.rectObj = QtWidgets.QGraphicsLineItem(self.parent)
            self.rectObj.setPen(QtGui.QPen(QtGui.QColor(*self.style["color"])))
            self.UpdateRect()

        self.setText(self.GetText())

        self.ApplyStyle()

    # update text with priorities: marker, track, label
    def GetText(self):
        # check for marker text entry
        if self.data.text is not None:
            return self.data.text

        # check for track text entry
        if self.data.track is not None and self.data.track.text is not None:
            return self.data.track.text

        # check for type text entry
        if self.data.type and self.data.type.text is not None:
            return self.data.type.text

        # check for type text entry
        if self.data.track and self.data.track.type.text is not None:
                return self.data.track.type.text

        # if there are no text entries return an empty string
        return ""


    def setText(self, text):
        if self.text is None:
            self.font = QtGui.QFont()
            self.font.setPointSize(10)
            self.text_parent = QtWidgets.QGraphicsPathItem(self)
            self.text_parent.setFlag(QtWidgets.QGraphicsItem.ItemIgnoresTransformations)
            self.text = QtWidgets.QGraphicsSimpleTextItem(self.text_parent)
            self.text.setFont(self.font)
            self.text.setPos(5, 5)
            self.text.setZValue(10)
            self.text.setBrush(QtGui.QBrush(self.color))

        # augment text
        if '$track_id' in text:
            if self.data.track and self.data.track.id:
                text = text.replace('$track_id', '%d' % self.data.track.id)
            else:
                text = text.replace('$track_id', '??')
        if '$marker_id' in text:
            if self.data.id:
                text = text.replace('$marker_id', '%d' % self.data.id)
            else:
                text = text.replace('$marker_id', '??')
        if '$x_pos' in text:
            text = text.replace('$x_pos', '%.2f' % self.data.x)
        if '$y_pos' in text:
            text = text.replace('$y_pos', '%.2f' % self.data.y)
        if '$line_length' in text:
            if self.data.partner_id:
                if self.data.x > self.data.partner.x:
                    text = text.replace('$line_length', '%.2f' % np.linalg.norm(
                        np.array([self.data.x, self.data.y]) - np.array(
                            [self.data.partner.x, self.data.partner.y])))
                else:
                    text = text.replace('$line_length', '')
            else:
                text = text.replace('$line_length', '??')
        if '\\n' in text:
            text = text.replace('\\n', '\n')

        self.text.setText(text)

    def GetStyle(self):
        self.style = {}

        # get style from marker type
        type = self.data.type if self.data.type else self.data.track.type
        if type and type.style:
            style_text = type.style
            try:
                type_style = json.loads(style_text)
            except ValueError:
                type_style = {}
                print("WARNING: type %d style could not be read: %s" % (type.id, style_text))
            self.style.update(type_style)

        # get style from marker
        if self.data.style:
            style_text = self.data.style
            try:
                marker_style = json.loads(style_text)
            except ValueError:
                marker_style = {}
                print("WARNING: marker %d style could not be read: %s" % (self.data.track.id, style_text))
            self.style.update(marker_style)

        # get color from old color field
        if "color" not in self.style and self.data.type:
            self.style["color"] = self.data.type.color
        else:
            self.style["color"] = "#FFFFFF"

        # change color text to rgb by interpreting it as html text or a color map
        if self.style["color"][0] != "#":
            self.style["color"] = GetColorFromMap(self.style["color"], self.data.id)
        else:
            self.style["color"] = HTMLColorToRGB(self.style["color"])

        # store color
        self.color = QtGui.QColor(*self.style["color"])

    def ReloadData(self):
        self.setPos(self.data.x, self.data.y)
        self.GetStyle()
        self.ApplyStyle()
        self.setText(self.GetText())

    def ApplyStyle(self):
        self.color = QtGui.QColor(*self.style["color"])
        if self.style.get("shape", "cross") == "cross":
            self.setBrush(QtGui.QBrush(self.color))
            self.setPen(QtGui.QPen(QtGui.QColor(0, 0, 0, 0)))
        else:
            self.setBrush(QtGui.QBrush(QtGui.QColor(0, 0, 0, 0)))
            self.setPen(QtGui.QPen(self.color, self.style.get("line-width", 1)))
        if self.text:
            self.text.setBrush(QtGui.QBrush(self.color))
        self.UpdatePath()
        self.setScale(None)

    def FindPartner(self):
        if self.data.partner_id:
            for point in self.marker_handler.points:
                if point.data.id == self.data.partner_id:
                    self.ConnectToPartner(point)
                    break
        if not self.data.partner_id:
            possible_partners = []
            for point in self.marker_handler.points:
                if point.data.type == self.data.type and point.partner is None:
                    possible_partners.append(
                        [point, np.linalg.norm(PosToArray(self.pos()) - PosToArray(point.pos()))])
            if len(possible_partners):
                possible_partners.sort(key=lambda x: x[1])
                self.ConnectToPartner(possible_partners[0][0])

    def ConnectToPartner(self, point, back=True):
        if not self.data.id:
            self.data.save()
        point.data.partner = self.data
        self.data.partner = point.data
        self.saved = False
        point.saved = False
        self.partner = point
        self.UseCrosshair = False
        if back:
            point.ConnectToPartner(self, back=False)

    def SetProcessed(self, processed):
        self.data.processed = processed

    def delete(self, just_display=False):
        # delete the database entry
        if not just_display:
            self.data.delete_instance()

        # delete from marker handler list
        self.marker_handler.RemoveFromList(self)

        # delete from scene
        self.scene().removeItem(self)

        # delete from counter
        self.marker_handler.GetCounter(self.data.type).AddCount(-1)

        # delete from partner
        if self.partner and self.partner.rectObj:
            self.marker_handler.view.scene.removeItem(self.partner.rectObj)
            self.partner.rectObj = None
            self.partner.partner = None
        if self.rectObj:
            self.partner.partner = None
            self.marker_handler.view.scene.removeItem(self.rectObj)

    def UpdateRect(self):
        x, y = self.pos().x(), self.pos().y()
        x2, y2 = self.partner.pos().x(), self.partner.pos().y()
        if self.data.type.mode & TYPE_Rect:
            self.rectObj.setRect(x, y, x2 - x, y2 - y)
        elif self.data.type.mode & TYPE_Line:
            self.rectObj.setLine(x, y, x2, y2)

    def mousePressEvent(self, event):
        if event.button() == 2:  # right mouse button
            # open marker edit menu
            if not self.marker_handler.marker_edit_window or not self.marker_handler.marker_edit_window.isVisible():
                self.marker_handler.marker_edit_window = MarkerEditor(self.marker_handler, self.marker_handler.marker_file)
                self.marker_handler.marker_edit_window.show()
            self.marker_handler.marker_edit_window.setMarker(self.data)
        if event.button() == 1:  # left mouse button
            # left click with Ctrl -> delete
            if event.modifiers() == QtCore.Qt.ControlModifier:
                self.delete()
            # left click -> move
            else:
                self.dragged = True
                self.drag_start_pos = event.pos()
                self.setCursor(QtGui.QCursor(QtCore.Qt.BlankCursor))
                if self.UseCrosshair:
                    self.marker_handler.Crosshair.Show(self)
                    self.marker_handler.Crosshair.MoveCrosshair(self.pos().x(), self.pos().y())

    def mouseMoveEvent(self, event):
        if not self.dragged:
            return
        pos = self.parent.mapFromItem(self, event.pos()-self.drag_start_pos)
        self.saved = False
        self.setPos(pos.x(), pos.y())
        self.data.x, self.data.y = pos.x(), pos.y()
        self.marker_handler.PointsUnsaved = True
        if self.data.type.mode & TYPE_Track:
            self.UpdateLine()
        self.setText(self.GetText())
        if self.UseCrosshair:
            self.marker_handler.Crosshair.MoveCrosshair(pos.x(), pos.y())
        if self.partner:
            if self.rectObj:
                self.UpdateRect()
            else:
                self.partner.UpdateRect()
                self.partner.setPos(self.partner.pos())
            self.partner.setText(self.partner.GetText())

    def mouseReleaseEvent(self, event):
        if event.button() == 1 and self.dragged:
            self.dragged = False
            self.marker_handler.PointsUnsaved = True
            self.SetProcessed(0)
            self.data.save()
            self.setCursor(QtGui.QCursor(QtCore.Qt.OpenHandCursor))
            self.marker_handler.Crosshair.Hide()
            pass

    def setActive(self, active):
        if active:
            self.setAcceptedMouseButtons(Qt.MouseButtons(3))
            #self.setCursor(QCursor(QtCore.Qt.OpenHandCursor))
        else:
            self.setAcceptedMouseButtons(Qt.MouseButtons(0))
            #self.unsetCursor()
        return True

    def UpdatePath(self):
        if point_display_type == 0:
            self.setPath(paths[self.style.get("shape", "cross")])
        else:
            self.setPath(point_display_types[point_display_type])

    def setScale(self, scale=None):
        if scale is not None:
            self.scale_value = scale
        if self.rectObj:
            self.rectObj.setPen(QtGui.QPen(self.color, 2 * self.scale_value))
        super(QtWidgets.QGraphicsPathItem, self).setScale(self.scale_value*self.style.get("scale", 1))

    def save(self):
        if not self.saved:
            self.data.save()

    def draw(self, image, start_x, start_y, scale=1):
        w = 1.*scale
        b = (10-7)*scale
        r2 = 10*scale
        x, y = self.pos().x()-start_x, self.pos().y()-start_y
        color = (self.color.red(), self.color.green(), self.color.blue())
        if self.partner:
            if self.rectObj:
                x2, y2 = self.partner.pos().x()-start_x, self.partner.pos().y()-start_y
                if self.data.type.mode & TYPE_Rect:
                    image.line([x , y , x2, y ], color, width=int(3*scale))
                    image.line([x , y2, x2, y2], color, width=int(3*scale))
                    image.line([x , y , x , y2], color, width=int(3*scale))
                    image.line([x2, y , x2, y2], color, width=int(3*scale))
                if self.data.type.mode & TYPE_Line:
                    image.line([x, y, x2, y2], color, width=int(3*scale))
            return
        image.rectangle([x-w, y-r2, x+w, y-b], color)
        image.rectangle([x-w, y+b, x+w, y+r2], color)
        image.rectangle([x-r2, y-w, x-b, y+w], color)
        image.rectangle([x+b, y-w, x+r2, y+w], color)


class MyTrackItem(MyMarkerItem):
    def __init__(self, marker_handler, parent, points_data, track, saved=False, frame=None):
        MyMarkerItem.__init__(self, marker_handler, parent, points_data[0])
        self.points_data = SortedDict()
        for point in points_data:
            self.points_data[point.image.sort_index] = point

        self.track = track
        self.track_style = {}
        self.UpdateStyle()
        self.current_frame = 0
        self.min_frame = min(self.points_data.keys())
        self.max_frame = max(self.points_data.keys())

        self.pathItem = QtWidgets.QGraphicsPathItem(self.parent)
        self.path = QtGui.QPainterPath()
        self.pathItem.setPen(QtGui.QPen(self.color))

        self.hidden = False
        self.active = True
        self.saved = saved

        self.FrameChanged(frame)

    def UpdateStyle(self):
        self.style = {}

        # get style from marker type
        if self.track.type.style:
            style_text = self.track.type.style
            try:
                type_style = json.loads(style_text)
            except ValueError:
                type_style = {}
                print("WARNING: type %d style could not be read: %s" % (self.track.type.id, style_text))
            self.style.update(type_style)

        # get style from track
        if self.track.style:
            style_text = self.data.track.style
            try:
                track_style = json.loads(style_text)
            except ValueError:
                track_style = {}
                print("WARNING: track %d style could not be read: %s" % (self.data.track.id, style_text))
            self.style.update(track_style)

        # get color from old color field
        if "color" not in self.style:
            self.style["color"] = self.track.type.color

        # change color text to rgb by interpreting it as html text or a color map
        if self.style["color"][0] != "#":
            self.style["color"] = GetColorFromMap(self.style["color"], self.track.id)
        else:
            self.style["color"] = HTMLColorToRGB(self.style["color"])

        # remember the style which is specific for the track before adding marker specific styles
        self.track_style = self.style.copy()

        # get style from current marker
        if self.data.style:
            style_text = self.data.style
            try:
                marker_style = json.loads(style_text)
            except ValueError:
                marker_style = {}
                print("WARNING: marker %d style could not be read: %s" % (self.data.track.id, style_text))
            self.style.update(marker_style)

        # convert html color to rgb
        if self.style["color"][0] == "#":
            self.style["color"] = HTMLColorToRGB(self.style["color"])

        # apply the style
        self.ApplyStyle()

    def FrameChanged(self, frame):

        self.current_frame = frame
        hide = not self.CheckToDisplay()
        if hide != self.hidden:
            self.hidden = hide
            self.setVisible(not self.hidden)
            self.pathItem.setVisible(not self.hidden)

        if frame in self.points_data:
            self.data = self.points_data[frame]
            self.setPos(self.data.x, self.data.y)
            self.UpdateLine()
            self.SetTrackActive(True)
            if self.partner and self.rectObj:
                self.UpdateRect()
            self.UpdateStyle()
            self.setText(self.GetText())
            return

        if not self.hidden:
            self.UpdateLine()
        self.SetTrackActive(False)
        self.data = self.marker_handler.marker_file.add_marker(x=self.pos().x(), y=self.pos().y(), type=self.track.type, track=self.track, text=None)
        #self.UpdateStyle()

    def update(self, frame, point=None):
        if point is not None:
            self.AddTrackPoint(frame, point)
            if frame == self.current_frame:
                self.ReloadData()
                self.UpdateStyle()
        else:
            self.RemoveTrackPoint(frame)
        self.UpdateLine()

    def AddTrackPoint(self, frame=None, point=None):
        if frame is None:
            frame = self.current_frame
        if point is None:
            point = self.data
        self.points_data[frame] = point
        self.min_frame = min(self.points_data.keys())
        self.max_frame = max(self.points_data.keys())
        if frame == self.current_frame:
            self.SetTrackActive(True)
        BroadCastEvent(self.marker_handler.modules, "MarkerPointsAdded")

    def delete(self, just_display=False):
        if not just_display:
            # delete all markers from this track
            self.marker_handler.data_file.table_marker.delete() \
                .where(self.marker_handler.data_file.table_marker.track == self.data.track.id) \
                .execute()

            # delete track entry
            self.marker_handler.data_file.table_track.delete() \
                .where(self.marker_handler.data_file.table_track.id == self.data.track.id) \
                .execute()

        # delete from marker handler list
        self.marker_handler.RemoveFromList(self)

        # delete from scene
        self.scene().removeItem(self)
        self.pathItem.scene().removeItem(self.pathItem)

        # delete from counter
        self.marker_handler.GetCounter(self.data.type).AddCount(-1)

        # delete from partner
        if self.partner and self.partner.rectObj:
            self.marker_handler.view.scene.removeItem(self.partner.rectObj)
            self.partner.rectObj = None
            self.partner.partner = None
        if self.rectObj:
            self.partner.partner = None
            self.marker_handler.view.scene.removeItem(self.rectObj)

    def RemoveTrackPoint(self, frame=None):
        # use the current frame if no frame is supplied
        if frame is None:
            frame = self.current_frame
        # delete the frame from points
        try:
            data = self.points_data.pop(frame)
            data.delete_instance()
        except KeyError:
            pass
        # if it was the last one delete the track, too
        if len(self.points_data) == 0:
            self.delete()
            return
        # adjust the frame range
        self.min_frame = min(self.points_data.keys())
        self.max_frame = max(self.points_data.keys())
        # set the track to inactive if the current marker was removed
        if frame == self.current_frame:
            self.saved = True
            self.SetTrackActive(False)
        # redraw the track history
        self.UpdateLine()

    def SetTrackActive(self, active):
        if active is False:
            self.active = False
            self.setOpacity(0.5)
            self.pathItem.setOpacity(0.25)
        else:
            self.active = True
            self.setOpacity(1)
            self.pathItem.setOpacity(0.5)

    def CheckToDisplay(self):
        if self.min_frame-2 <= self.current_frame <= self.max_frame+100:
            return True
        return False

    def UpdateLine(self):
        self.path = QtGui.QPainterPath()
        circle_width = self.scale_value * 10 * self.track_style.get("track-point-scale", 1)
        last_frame = None
        shape = self.track_style.get("track-point-shape", "circle")
        for frame in self.points_data:
            if self.config.tracking_show_trailing != -1 and frame < self.current_frame-self.config.tracking_show_trailing:
                continue
            if self.config.tracking_show_leading != -1 and frame > self.current_frame+self.config.tracking_show_leading:
                break
            point = self.points_data[frame]
            if last_frame == frame-1:
                self.path.lineTo(point.x, point.y)
            else:
                self.path.moveTo(point.x, point.y)
            last_frame = frame
            if shape == "circle":
                self.path.addEllipse(point.x - .5 * circle_width, point.y - .5 * circle_width, circle_width, circle_width)
            if shape == "rect":
                self.path.addRect(point.x - .5 * circle_width, point.y - .5 * circle_width, circle_width, circle_width)
            self.path.moveTo(point.x, point.y)
        self.pathItem.setPath(self.path)

    def draw(self, image, start_x, start_y, scale=1):
        if not self.CheckToDisplay():
            return
        if self.partner:
            return MyMarkerItem.draw(self, image, start_x, start_y, scale)
        color = (self.color.red(), self.color.green(), self.color.blue())
        circle_width = 10*scale
        last_frame = None
        last_point = np.array([0, 0])
        offset = np.array([start_x, start_y])
        for frame in self.points_data:
            if self.config.tracking_show_trailing != -1 and frame < self.current_frame-self.config.tracking_show_trailing:
                continue
            if self.config.tracking_show_leading != -1 and frame > self.current_frame+self.config.tracking_show_leading:
                break
            point = self.points_data[frame]
            point = np.array([point.x, point.y])-offset

            if last_frame == frame-1:
                image.line(np.concatenate((last_point, point)).tolist(), color, width=int(2*scale))
            image.arc(np.concatenate((point-.5*circle_width, point+.5*circle_width)).tolist(), 0, 360, color)
            last_point = point
            last_frame = frame
        if self.active:
            MyMarkerItem.draw(self, image, start_x, start_y, scale)

    def mousePressEvent(self, event):
        if event.button() == 1:
            if not event.modifiers() & Qt.ControlModifier:
                if self.active is False:
                    self.AddTrackPoint()
                    self.saved = False
            else:
                return self.RemoveTrackPoint()
        MyMarkerItem.mousePressEvent(self, event)

    def mouseMoveEvent(self, event):
        if self.dragged:
            if self.active is False:
                self.AddTrackPoint()
            self.saved = False
            self.UpdateLine()
        MyMarkerItem.mouseMoveEvent(self, event)

    def setCurrentPoint(self, x, y):
        self.setPos(x, y)
        self.data.x, self.data.y = x, y
        if self.active is False:
            self.AddTrackPoint()
            self.saved = False
        self.UpdateLine()

    def setScale(self, scale):
        MyMarkerItem.setScale(self, scale)
        try:
            line_styles = dict(solid=Qt.SolidLine, dash=Qt.DashLine, dot=Qt.DotLine, dashdot=Qt.DashDotLine, dashdotdot=Qt.DashDotDotLine)
            line_style = line_styles[self.track_style.get("track-line-style", "solid")]
            line_width = self.track_style.get("track-line-width", 2)
            self.pathItem.setPen(QtGui.QPen(QtGui.QColor(*self.track_style["color"]), line_width * self.scale_value, line_style))
            self.UpdateLine()
        except AttributeError:
            pass

    def save(self):
        if not self.saved:
            try:
                self.data.save()
            except peewee.IntegrityError:
                pass
            self.saved = True


class Crosshair(QtWidgets.QGraphicsPathItem):
    def __init__(self, parent, view, image, config):
        QtWidgets.QGraphicsPathItem.__init__(self, parent)
        self.parent = parent
        self.view = view
        self.image = image
        self.config = config
        self.radius = 50
        self.not_scaled = True
        self.scale = 1

        self.RGB = np.zeros((self.radius * 2 + 1, self.radius * 2 + 1, 3))
        self.Alpha = disk(self.radius) * 255
        self.Image = np.concatenate((self.RGB, self.Alpha[:, :, None]), axis=2)
        self.CrosshairQImage = array2qimage(self.Image)
        self.CrosshairQImageView = rgb_view(self.CrosshairQImage)

        self.Crosshair = QtWidgets.QGraphicsPixmapItem(QtGui.QPixmap(self.CrosshairQImage), self)
        self.Crosshair.setOffset(-self.radius, -self.radius)
        self.setPos(self.radius * 3, self.radius * 3)
        self.Crosshair.setZValue(-5)
        self.setZValue(30)
        self.setVisible(False)

        self.pathCrosshair = QtGui.QPainterPath()
        self.pathCrosshair.addEllipse(-self.radius, -self.radius, self.radius * 2, self.radius * 2)

        w = 0.333 * 0.5
        b = 40
        r2 = 50
        self.pathCrosshair2 = QtGui.QPainterPath()
        self.pathCrosshair2.addRect(-r2, -w, b, w * 2)
        self.pathCrosshair2.addRect(r2, -w, -b, w * 2)
        self.pathCrosshair2.addRect(-w, -r2, w * 2, b)
        self.pathCrosshair2.addRect(-w, r2, w * 2, -b)

        self.CrosshairPathItem = QtWidgets.QGraphicsPathItem(self.pathCrosshair, self)
        # self.setPath(self.pathCrosshair)
        self.CrosshairPathItem2 = QtWidgets.QGraphicsPathItem(self.pathCrosshair2, self)

    def setScale(self, value):
        QtWidgets.QGraphicsPathItem.setScale(self, value)
        self.scale = value
        if not self.SetZoom(value):
            QtWidgets.QGraphicsPathItem.setScale(self, 0)
        return True

    def SetZoom(self, new_radius=None):
        if new_radius is not None:
            self.radius = int(new_radius * 50 / 3)
        if not self.isVisible():
            self.not_scaled = True
            return False
        self.not_scaled = False
        if self.radius <= 10:
            return False
        self.RGB = np.zeros((self.radius * 2 + 1, self.radius * 2 + 1, 3))
        self.Alpha = disk(self.radius) * 255
        self.Image = np.concatenate((self.RGB, self.Alpha[:, :, None]), axis=2)
        self.CrosshairQImage = array2qimage(self.Image)
        self.CrosshairQImageView = rgb_view(self.CrosshairQImage)
        self.Crosshair.setPixmap(QtGui.QPixmap(self.CrosshairQImage))
        self.Crosshair.setScale(1 / self.radius * 50)
        self.Crosshair.setOffset(-self.radius - 0.5, -self.radius - 0.5)
        self.MoveCrosshair(self.pos().x(), self.pos().y())
        return True

    def MoveCrosshair(self, x, y):
        y = int(y)
        x = int(x)
        self.setPos(x, y)
        if not self.isVisible() or self.radius <= 10:
            return
        self.CrosshairQImageView[:, :, :] = self.SaveSlice(self.image.image,
                                                           [[y - self.radius, y + self.radius + 1],
                                                            [x - self.radius, x + self.radius + 1], [0, 3]])
        self.Crosshair.setPixmap(QtGui.QPixmap(self.CrosshairQImage))

    @staticmethod
    def SaveSlice(source, slices):
        shape = []
        slices1 = []
        slices2 = []
        empty = False
        for length, slice_border in zip(source.shape, slices):
            slice_border = [int(b) for b in slice_border]
            shape.append(slice_border[1] - slice_border[0])
            if slice_border[1] < 0:
                empty = True
            slices1.append(slice(max(slice_border[0], 0), min(slice_border[1], length)))
            slices2.append(slice(-min(slice_border[0], 0),
                                 min(length - slice_border[1], 0) if min(length - slice_border[1], 0) != 0 else shape[
                                     -1]))
        new_slice = np.zeros(shape)
        if empty:
            return new_slice
        new_slice[slices2[0], slices2[1], :] = source[slices1[0], slices1[1], :3]
        return new_slice

    def Hide(self):
        self.setVisible(False)

    def Show(self, point):
        self.setVisible(True)
        if self.not_scaled:
            if self.SetZoom():
                self.setScale(self.scale)
            else:
                self.setScale(0)
        self.CrosshairPathItem2.setPen(QtGui.QPen(point.color))
        self.CrosshairPathItem.setPen(QtGui.QPen(point.color))


class MyCounter(QtWidgets.QGraphicsRectItem):
    def __init__(self, parent, marker_handler, type, index):
        QtWidgets.QGraphicsRectItem.__init__(self, parent)
        self.parent = parent
        self.marker_handler = marker_handler
        self.type = type
        self.index = index
        self.count = 0
        self.setCursor(QtGui.QCursor(QtCore.Qt.ArrowCursor))

        self.setAcceptHoverEvents(True)
        self.active = False

        self.font = self.marker_handler.window.mono_font
        self.font.setPointSize(14)

        self.text = QtWidgets.QGraphicsSimpleTextItem(self)
        self.text.setFont(self.font)
        if self.type is not None:
            self.color = QtGui.QColor(*HTMLColorToRGB(self.type.color))
        else:
            self.color = QtGui.QColor("white")
        self.text.setBrush(QtGui.QBrush(self.color))
        self.text.setZValue(10)

        self.setBrush(QtGui.QBrush(QtGui.QColor(0, 0, 0, 128)))
        self.setPos(10, 10 + 25 * self.index)
        self.setZValue(9)

        count = 0
        if self.type:
            for point in self.marker_handler.points:
                if point.data.type == self.type:
                    count += 1
        self.AddCount(count)

    def AddCount(self, new_count):
        self.count += new_count
        if self.type:
            self.text.setText(
                str(self.index+1) + ": " + self.type.name + " %d" % self.count)
        else:
            self.text.setText("+ add type")
        rect = self.text.boundingRect()
        rect.setX(-5)
        rect.setWidth(rect.width() + 5)
        self.setRect(rect)

    def SetToActiveColor(self):
        self.active = True
        self.setBrush(QtGui.QBrush(QtGui.QColor(255, 255, 255, 128)))

    def SetToInactiveColor(self):
        self.active = False
        self.setBrush(QtGui.QBrush(QtGui.QColor(0, 0, 0, 128)))

    def hoverEnterEvent(self, event):
        if self.active is False:
            self.setBrush(QtGui.QBrush(QtGui.QColor(128, 128, 128, 128)))

    def hoverLeaveEvent(self, event):
        if self.active is False:
            self.setBrush(QtGui.QBrush(QtGui.QColor(0, 0, 0, 128)))

    def mousePressEvent(self, event):
        if event.button() == 2 or self.type is None:
            if not self.marker_handler.marker_edit_window or not self.marker_handler.marker_edit_window.isVisible():
                self.marker_handler.marker_edit_window = MarkerEditor(self.marker_handler, self.marker_handler.marker_file)
                self.marker_handler.marker_edit_window.show()
            self.marker_handler.marker_edit_window.setMarker(self.type, data_type="type")
        elif event.button() == 1:
            if not self.marker_handler.active:
                BroadCastEvent([module for module in self.marker_handler.modules if module != self.marker_handler], "setActiveModule", False)
                self.marker_handler.setActiveModule(True)
            self.marker_handler.SetActiveMarkerType(self.index)
            if self.marker_handler.marker_edit_window:
                self.marker_handler.marker_edit_window.setMarker(self.type, data_type="type")


class MarkerHandler:
    points = []
    tracks = []
    counter = []
    scale = 1

    text = None
    marker_edit_window = None

    active = False
    frame_number = None
    hidden = False

    active_type_index = None
    active_type = None

    def __init__(self, window, data_file, parent, parent_hud, view, image_display, config, modules, datafile, new_database):
        self.window = window
        self.data_file = data_file
        self.view = view
        self.parent_hud = parent_hud
        self.modules = modules
        self.config = config
        self.data_file = datafile
        self.parent = parent

        self.button = QtWidgets.QPushButton()
        self.button.setCheckable(True)
        self.button.setIcon(qta.icon("fa.crosshairs"))
        self.button.setToolTip("add/edit marker for current frame")
        self.button.clicked.connect(self.ToggleInterfaceEvent)
        self.window.layoutButtons.addWidget(self.button)

        self.marker_file = MarkerFile(datafile)

        if self.config.hide_interfaces:
            self.hidden = True

        self.MarkerParent = QtWidgets.QGraphicsPixmapItem(QtGui.QPixmap(array2qimage(np.zeros([1, 1, 4]))), self.parent)
        self.MarkerParent.setZValue(10)

        self.TrackParent = QtWidgets.QGraphicsPixmapItem(QtGui.QPixmap(array2qimage(np.zeros([1, 1, 4]))), self.parent)
        self.TrackParent.setZValue(10)

        self.scene_event_filter = GraphicsItemEventFilter(parent, self)
        image_display.AddEventFilter(self.scene_event_filter)

        self.Crosshair = Crosshair(parent, view, image_display, config)

        # if a new database is created fill it with markers from the config
        if new_database:
            for type_id, type_def in self.config.types.items():
                self.marker_file.set_type(type_id, type_def[0], type_def[1], type_def[2])

        self.UpdateCounter()

        # place tick marks for already present markers
        for item in self.marker_file.get_marker_frames():
            BroadCastEvent(self.modules, "MarkerPointsAdded", item.image.sort_index)

    def drawToImage(self, image, start_x, start_y, scale=1):
        for point in self.points:
            point.draw(image, start_x, start_y, scale)
        for track in self.tracks:
            track.draw(image, start_x, start_y, scale)

    def UpdateCounter(self):
        for counter in self.counter:
            self.view.scene.removeItem(self.counter[counter])

        type_list = self.marker_file.get_type_list()
        self.counter = {index: MyCounter(self.parent_hud, self, type, index) for index, type in enumerate(type_list)}
        self.counter[-1] = MyCounter(self.parent_hud, self, None, len(self.counter))
        if len(list(self.counter.keys())):
            self.active_type = self.counter[list(self.counter.keys())[0]].type
        else:
            self.active_type = None

        for key in self.counter:
            self.counter[key].setVisible(not self.hidden)

    def GetCounter(self, type):
        for index in self.counter:
            if self.counter[index].type == type:
                return self.counter[index]
        raise NameError("A non existing type was referenced")

    def ReloadMarker(self, frame=None):
        if frame is None:
            frame = self.data_file.get_current_image()
            image_id = self.data_file.image.id
        else:
            image_id = self.data_file.get_image(frame).id
        # Tracks
        marker_list = self.marker_file.get_marker_list(image_id)
        marker_list = {marker.track.id: marker for marker in marker_list if marker.track}
        for track in self.tracks:
            if track.track.id in marker_list:
                track.update(frame, marker_list[track.track.id])
                marker_list.pop(track.track.id)
            else:
                track.update(frame, None)
        # Points
        if frame == self.frame_number:
            self.LoadPoints()

    def LoadImageEvent(self, filename, framenumber):
        self.frame_number = framenumber
        image = self.data_file.image

        if len(self.tracks) == 0:
            self.LoadTracks()
        else:
            for track in self.tracks:
                track.FrameChanged(framenumber)
        self.LoadPoints()

    def LoadTracks(self):
        while len(self.tracks):
            self.tracks[0].delete(just_display=True)
        track_list = self.marker_file.table_track.select()
        for track in track_list:
            data = track.markers
            if data.count():
                self.tracks.append(MyTrackItem(self, self.TrackParent, data, track, saved=True, frame=self.frame_number))
                self.tracks[-1].setScale(1 / self.scale)

    def ReloadTrack(self, track):
        track_item = self.GetTrackItem(track)
        track_item.delete(just_display=True)
        data = track.markers
        if data.count():
            self.tracks.append(MyTrackItem(self, self.TrackParent, data, track, saved=True, frame=self.frame_number))
            self.tracks[-1].setScale(1 / self.scale)

    def LoadPoints(self):
        while len(self.points):
            self.points[0].delete(just_display=True)
        marker_list = (self.marker_file.table_marker.select(self.marker_file.table_marker, self.marker_file.table_markertype)
            .join(self.marker_file.table_markertype)
            .where(self.marker_file.table_marker.image == self.data_file.image.id)
            )
        for marker in marker_list:
            if not marker.track:
                self.points.append(MyMarkerItem(self, self.MarkerParent, marker, saved=True))
                self.points[-1].setScale(1 / self.scale)

    def ClearPoints(self):
        self.points = []
        self.view.scene.removeItem(self.MarkerParent)
        self.MarkerParent = QtWidgets.QGraphicsPixmapItem(QtGui.QPixmap(array2qimage(np.zeros([1, 1, 4]))), self.parent)
        self.MarkerParent.setZValue(10)

    def RemoveFromList(self, point):
        try:
            self.points.remove(point)
        except ValueError:
            self.tracks.remove(point)

    def GetMarkerItem(self, data):
        for point in self.points:
            if point.data.id == data.id:
                return point

    def GetTrackItem(self, data):
        for track in self.tracks:
            if track.track.id == data.id:
                return track

    def save(self):
        for point in self.points:
            point.save()
        for track in self.tracks:
            track.save()

    def SetActiveMarkerType(self, new_index):
        if new_index >= len(self.counter)-1:
            return
        if self.active_type_index is not None:
            self.counter[self.active_type_index].SetToInactiveColor()
        self.active_type = self.counter[new_index].type
        self.active_type_index = new_index
        self.counter[self.active_type_index].SetToActiveColor()

    def zoomEvent(self, scale, pos):
        self.scale = scale
        for point in self.points:
            point.setScale(1 / scale)
        for track in self.tracks:
            track.setScale(1 / scale)
        self.Crosshair.setScale(1 / scale)

    def setActiveModule(self, active, first_time=False):
        self.scene_event_filter.active = active
        self.active = active
        for point in self.points:
            point.setActive(active)
        if active:
            self.view.setCursor(QtGui.QCursor(QtCore.Qt.ArrowCursor))
            if self.active_type_index is not None:
                self.counter[self.active_type_index].SetToActiveColor()
        else:
            if self.active_type_index is not None:
                self.counter[self.active_type_index].SetToInactiveColor()
        return True

    def toggleMarkerShape(self):
        global point_display_type
        point_display_type += 1
        if point_display_type >= len(point_display_types):
            point_display_type = 0
        for point in self.points:
            point.UpdatePath()
        for track in self.tracks:
            track.UpdatePath()

    def sceneEventFilter(self, event):
        if self.hidden:
            return False
        if event.type() == 156 and event.button() == 1 and not event.modifiers() & Qt.ControlModifier:  # QtCore.QEvent.MouseButtonPress:
            if len(self.points) >= 0:
                BroadCastEvent(self.modules, "MarkerPointsAdded")
            tracks = [track for track in self.tracks if track.data.type.id == self.active_type.id]
            if self.active_type.mode & TYPE_Track and self.config.tracking_connect_nearest and \
                    len(tracks) and not event.modifiers() & Qt.AltModifier:
                distances = [np.linalg.norm(PosToArray(point.pos() - event.pos())) for point in tracks]
                index = np.argmin(distances)
                tracks[index].setCurrentPoint(event.pos().x(), event.pos().y())
            elif self.active_type.mode & TYPE_Track:
                track = self.marker_file.set_track(self.active_type)
                data = self.marker_file.add_marker(x=event.pos().x(), y=event.pos().y(), type=self.active_type, track=track)
                self.tracks.append(MyTrackItem(self, self.TrackParent, [data], track, saved=False, frame=self.frame_number))
                self.tracks[-1].setScale(1 / self.scale)
                self.tracks[-1].save()
            else:
                data = self.marker_file.add_marker(x=event.pos().x(), y=event.pos().y(), type=self.active_type, text=self.text)
                self.points.append(MyMarkerItem(self, self.MarkerParent, data, saved=False))
                self.points[-1].setScale(1 / self.scale)
                self.points[-1].save()
            return True
        return False

    def keyPressEvent(self, event):

        numberkey = event.key() - 49

        # @key ---- Marker ----
        if self.active and 0 <= numberkey < 9 and event.modifiers() != Qt.KeypadModifier:
            # @key 0-9: change marker type
            self.SetActiveMarkerType(numberkey)

        if event.key() == QtCore.Qt.Key_T:
            # @key T: toggle marker shape
            self.toggleMarkerShape()
            
    def ToggleInterfaceEvent(self):
        self.hidden = not self.hidden
        for key in self.counter:
            self.counter[key].setVisible(not self.hidden)
        for point in self.points:
            point.setActive(not self.hidden)
        for track in self.tracks:
            track.setActive(not self.hidden)
        self.button.setChecked(not self.hidden)

    def loadLast(self):
        return("ERROR: not implemented at the moment")

    def canLoadLast(self):
        return self.last_logname is not None

    def closeEvent(self, event):
        if self.marker_edit_window:
            self.marker_edit_window.close()

    @staticmethod
    def file():
        return __file__

    @staticmethod
    def can_create_module(config):
        return len(config.types) > 0
