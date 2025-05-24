# Network Protocols (ECE-5372)
# The University of Texas at El Paso
# 
# Final Project: Mininet Network Topology Editor
# Created by: 
# - Ivan Mendoza
# - Pablo Sotelo Torres
# - Luis Garza Garcia
# 
# Description:
# Our team was tasked with creating a Mininet Topology Editor that allows users
# to design network topologies through a graphical interface and simulate them using
# Mininet. The final product is a GUI built in Python/Qt that allows users to
# manually draw or generate topologies, which are saved as JSON files and passed to
# Mininet for simulation. Alternatively, the user can load a topology from a JSON
# file and visualize it on the canvas.
# 
# Project Adapted from Qt for Python Diagram Scene Example
# Source: https://doc.qt.io/qtforpython-6/examples/example_widgets_graphicsview_diagramscene.html
# 
# Copyright (C) 2013 Riverbank Computing Limited.
# Copyright (C) 2022 The Qt Company Ltd.
# SPDX-License-Identifier: LicenseRef-Qt-Commercial OR BSD-3-Clause

from __future__ import annotations

import math
import sys
import json
import networkx as nx

import re
import subprocess
import os

from PySide6.QtCore import (QLineF, QPointF, QRect, QRectF, QSize, QSizeF, Qt,
                            Signal, Slot)
from PySide6.QtGui import (QAction, QBrush, QColor, QFont, QIcon, QIntValidator,
                           QPainter, QPainterPath, QPen, QPixmap, QPolygonF)
from PySide6.QtWidgets import (QAbstractButton, QApplication, QButtonGroup,
                               QComboBox, QFontComboBox, QGraphicsItem, QGraphicsLineItem,
                               QGraphicsPolygonItem, QGraphicsTextItem,
                               QGraphicsScene, QGraphicsView, QGridLayout,
                               QHBoxLayout, QLabel, QMainWindow, QMenu,
                               QMessageBox, QSizePolicy, QToolBox, QToolButton,
                               QWidget, QGraphicsPixmapItem, QFileDialog, QInputDialog)

import network_editor_rc  # noqa: F401

# -------- Option 1: s1/flat --------
def generate_links_flat(num_hosts, num_switches):
    links = []
    for i in range(1, num_hosts + 1):
        links.append(["h" + str(i), "s1"])
    return links

# -------- Option 2: Subnet --------
def generate_links_subnets(num_subnets, hosts_per_subnet):
    links = []
    host_id = 1

    for subnet_id in range(1, num_subnets + 1):
        switch = "s" + str(subnet_id)
        for _ in range(hosts_per_subnet):
            host = "h" + str(host_id)
            links.append([host, switch])
            host_id += 1

    # Central switch
    central_switch = f"s{num_subnets + 1}"
    for subnet_id in range(1, num_subnets + 1):
        links.append([f"s{subnet_id}", central_switch])

    return links


class Arrow(QGraphicsLineItem):
    def __init__(self, startItem, endItem, parent=None, scene=None):
        super().__init__(parent, scene)

        self._arrow_head = QPolygonF()

        self._my_start_item = startItem
        self._my_end_item = endItem
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self._my_color = Qt.GlobalColor.black
        self.setPen(QPen(self._my_color, 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))

    def set_color(self, color):
        self._my_color = color
        self.setPen(QPen(self._my_color, 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))

    def start_item(self):
        return self._my_start_item

    def end_item(self):
        return self._my_end_item

    def update_position(self):
        start = self._my_start_item.sceneBoundingRect().center()
        end = self._my_end_item.sceneBoundingRect().center()
        self.setLine(QLineF(start, end))

    def paint(self, painter, option, widget=None):
        self.update_position()
        painter.setPen(self.pen())
        painter.drawLine(self.line())

        if self.isSelected():
            my_pen = QPen(self._my_color, 1, Qt.DashLine)
            painter.setPen(my_pen)
            my_line = QLineF(self.line())
            my_line.translate(0, 4.0)
            painter.drawLine(my_line)
            my_line.translate(0, -8.0)
            painter.drawLine(my_line)

class DiagramTextItem(QGraphicsTextItem):
    lost_focus = Signal(QGraphicsTextItem)

    selected_change = Signal(QGraphicsItem)

    def __init__(self, parent=None, scene=None):
        super().__init__(parent, scene)

        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemSelectedChange:
            self.selected_change.emit(self)
        return value

    def focusOutEvent(self, event):
        self.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        self.lost_focus.emit(self)
        super(DiagramTextItem, self).focusOutEvent(event)

    def mouseDoubleClickEvent(self, event):
        if self.textInteractionFlags() == Qt.TextInteractionFlag.NoTextInteraction:
            self.setTextInteractionFlags(Qt.TextInteractionFlag.TextEditorInteraction)
        super(DiagramTextItem, self).mouseDoubleClickEvent(event)

class DiagramImageItem(QGraphicsPixmapItem):
    def __init__(self, image_path, contextMenu, diagram_type, parent=None, scene=None):
        super().__init__(parent)
        self.id = None  # Initialize the id attribute

        self.arrows = []
        
        self.setPixmap(QPixmap(image_path).scaled(80, 80, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self._my_context_menu = contextMenu
        self.diagram_type = diagram_type

        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)

        self.label = QGraphicsTextItem("", self)
        self.label.setDefaultTextColor(Qt.black)
        self.label.setPos(0, self.pixmap().height() + 2)

    def set_label(self, id):
        self.label.setPlainText(id)
        label_width = self.label.boundingRect().width()
        image_width = self.pixmap().width()
        self.label.setPos((image_width - label_width) / 2, self.pixmap().height() + 4)

    def remove_arrow(self, arrow):
        try:
            self.arrows.remove(arrow)
        except ValueError:
            pass

    def remove_arrows(self):
        for arrow in self.arrows[:]:
            arrow.start_item().remove_arrow(arrow)
            arrow.end_item().remove_arrow(arrow)
            self.scene().removeItem(arrow)

    def add_arrow(self, arrow):
        self.arrows.append(arrow)

    def contextMenuEvent(self, event):
        self.scene().clearSelection()
        self.setSelected(True)
        self._my_context_menu.exec(event.screenPos())

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange:
            for arrow in self.arrows:
                arrow.update_position()

        return super().itemChange(change, value)

class DiagramItem(QGraphicsPolygonItem):
    Host, Switch, StartEnd, Io = range(4)

    def __init__(self, diagram_type, contextMenu, parent=None, scene=None):
        super().__init__(parent, scene)

        self.arrows = []

        self.diagram_type = diagram_type
        self._my_context_menu = contextMenu

        path = QPainterPath()
        if self.diagram_type == self.StartEnd:
            path.moveTo(200, 50)
            path.arcTo(150, 0, 50, 50, 0, 90)
            path.arcTo(50, 0, 50, 50, 90, 90)
            path.arcTo(50, 50, 50, 50, 180, 90)
            path.arcTo(150, 50, 50, 50, 270, 90)
            path.lineTo(200, 25)
            self._my_polygon = path.toFillPolygon()
        elif self.diagram_type == self.Switch:
            self._my_polygon = QPolygonF([
                QPointF(-100, 0), QPointF(0, 100),
                QPointF(100, 0), QPointF(0, -100),
                QPointF(-100, 0)])
        elif self.diagram_type == self.Host:
            self._my_polygon = QPolygonF([
                QPointF(-100, -100), QPointF(100, -100),
                QPointF(100, 100), QPointF(-100, 100),
                QPointF(-100, -100)])
        else:
            self._my_polygon = QPolygonF([
                QPointF(-120, -80), QPointF(-70, 80),
                QPointF(120, 80), QPointF(70, -80),
                QPointF(-120, -80)])

        self.setPolygon(self._my_polygon)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)

    def remove_arrow(self, arrow):
        try:
            self.arrows.remove(arrow)
        except ValueError:
            pass

    def remove_arrows(self):
        for arrow in self.arrows[:]:
            arrow.start_item().remove_arrow(arrow)
            arrow.end_item().remove_arrow(arrow)
            self.scene().removeItem(arrow)

    def add_arrow(self, arrow):
        self.arrows.append(arrow)

    def image(self):
        pixmap = QPixmap(250, 250)
        pixmap.fill(Qt.GlobalColor.transparent)
        with QPainter(pixmap) as painter:
            painter.setPen(QPen(Qt.GlobalColor.black, 8))
            painter.translate(125, 125)
            painter.drawPolyline(self._my_polygon)
        return pixmap

    def contextMenuEvent(self, event):
        self.scene().clearSelection()
        self.setSelected(True)
        self._my_context_menu.exec(event.screenPos())

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange:
            for arrow in self.arrows:
                arrow.update_position()

        return value

class DiagramScene(QGraphicsScene):
    InsertItem, InsertLine, InsertText, MoveItem = range(4)

    item_inserted = Signal(DiagramItem)

    text_inserted = Signal(QGraphicsTextItem)

    item_selected = Signal(QGraphicsItem)

    def __init__(self, itemMenu, parent=None):
        super().__init__(parent)

        self._my_item_menu = itemMenu
        self._my_mode = self.MoveItem
        self._my_item_type = DiagramItem.Host
        self.line = None
        self._text_item = None
        self._my_item_color = Qt.GlobalColor.white
        self._my_text_color = Qt.GlobalColor.black
        self._my_line_color = Qt.GlobalColor.black
        self._my_font = QFont()
        self.host_counter = 1
        self.switch_counter = 1

        self.available_switches = set()
        self.available_hosts = set()

    def set_line_color(self, color):
        self._my_line_color = color
        if self.is_item_change(Arrow):
            item = self.selectedItems()[0]
            item.set_color(self._my_line_color)
            self.update()

    def set_text_color(self, color):
        self._my_text_color = color
        if self.is_item_change(DiagramTextItem):
            item = self.selectedItems()[0]
            item.setDefaultTextColor(self._my_text_color)

    def set_item_color(self, color):
        self._my_item_color = color
        if self.is_item_change(DiagramItem):
            item = self.selectedItems()[0]
            item.setBrush(self._my_item_color)

    def set_font(self, font):
        self._my_font = font
        if self.is_item_change(DiagramTextItem):
            item = self.selectedItems()[0]
            item.setFont(self._my_font)

    def set_mode(self, mode):
        self._my_mode = mode

    def set_item_type(self, type):
        self._my_item_type = type

    def editor_lost_focus(self, item):
        cursor = item.textCursor()
        cursor.clearSelection()
        item.setTextCursor(cursor)

        if not item.toPlainText():
            self.removeItem(item)
            item.deleteLater()

    def mousePressEvent(self, mouseEvent):
        if (mouseEvent.button() != Qt.MouseButton.LeftButton):
            return

        if self._my_mode == self.InsertItem:

            if self._my_item_type == DiagramItem.Switch: # Switch

                item = DiagramImageItem(':/images/switch.png', self._my_item_menu, DiagramItem.Switch)

                if self.available_switches:
                    switch_id = self.available_switches.pop()
                else:
                    switch_id = f"s{self.switch_counter}"
                    self.switch_counter += 1

                item.id = switch_id
                item.set_label(switch_id)
                print(item.id)

            elif self._my_item_type == DiagramItem.Host: # Host

                item = DiagramImageItem(':/images/host.png', self._my_item_menu, DiagramItem.Host)

                if self.available_hosts:
                    host_id = sorted(self.available_hosts, key=lambda x: int(x[1:]))[0]
                    self.available_hosts.remove(host_id)
                else:
                    host_id = f"h{self.host_counter}"
                    self.host_counter += 1
                    
                item.id = host_id
                item.set_label(host_id)
                print(item.id)

            else:
                item = DiagramItem(self._my_item_type, self._my_item_menu)
            
            if isinstance(item, DiagramItem): # Only Polygons can have brush
                item.setBrush(self._my_item_color)
            
            self.addItem(item)
            item.setPos(mouseEvent.scenePos())
            self.item_inserted.emit(item)
        elif self._my_mode == self.InsertLine:
            self.line = QGraphicsLineItem(QLineF(mouseEvent.scenePos(), mouseEvent.scenePos()))
            self.line.setPen(QPen(self._my_line_color, 2))
            self.addItem(self.line)
        elif self._my_mode == self.InsertText:
            text_item = DiagramTextItem()
            text_item.setFont(self._my_font)
            text_item.setTextInteractionFlags(Qt.TextInteractionFlag.TextEditorInteraction)
            text_item.setZValue(1000.0)
            text_item.lost_focus.connect(self.editor_lost_focus)
            text_item.selected_change.connect(self.item_selected)
            self.addItem(text_item)
            text_item.setDefaultTextColor(self._my_text_color)
            text_item.setPos(mouseEvent.scenePos())
            self.text_inserted.emit(text_item)

        super(DiagramScene, self).mousePressEvent(mouseEvent)

    def mouseMoveEvent(self, mouseEvent):
        if self._my_mode == self.InsertLine and self.line:
            new_line = QLineF(self.line.line().p1(), mouseEvent.scenePos())
            self.line.setLine(new_line)
        elif self._my_mode == self.MoveItem:
            super(DiagramScene, self).mouseMoveEvent(mouseEvent)

    def mouseReleaseEvent(self, mouseEvent):
        if self.line and self._my_mode == self.InsertLine:
            start_items = self.items(self.line.line().p1())
            if len(start_items) and start_items[0] == self.line:
                start_items.pop(0)
            end_items = self.items(self.line.line().p2())
            if len(end_items) and end_items[0] == self.line:
                end_items.pop(0)

            self.removeItem(self.line)
            self.line = None

            if (len(start_items) and len(end_items)
                    and isinstance(start_items[0], (DiagramItem, DiagramImageItem))
                    and isinstance(end_items[0], (DiagramItem, DiagramImageItem))
                    and start_items[0] != end_items[0]):
                start_item = start_items[0]
                end_item = end_items[0]
                arrow = Arrow(start_item, end_item)
                arrow.set_color(self._my_line_color)
                start_item.add_arrow(arrow)
                end_item.add_arrow(arrow)
                arrow.setZValue(-1000.0)
                self.addItem(arrow)
                arrow.update_position()

        self.line = None
        super(DiagramScene, self).mouseReleaseEvent(mouseEvent)

    def is_item_change(self, type):
        for item in self.selectedItems():
            if isinstance(item, type):
                return True
        return False


class MainWindow(QMainWindow):
    insert_text_button = 10
    insert_line_button = 11

    def __init__(self):
        super().__init__()

        self.host_counter = 1
        self.switch_counter = 1
        self.available_switches = set()
        self.available_hosts = set()

        self._pointer_type_group = QButtonGroup()
        self._pointer_type_group.setExclusive(True)
        self._pointer_type_group.idClicked.connect(self.pointer_group_clicked)

        self.create_actions()
        self.create_menus()
        self.create_tool_box()

        self.scene = DiagramScene(self._item_menu)
        self.scene.setSceneRect(QRectF(0, 0, 5000, 5000))
        self.scene.item_inserted.connect(self.item_inserted)
        self.scene.text_inserted.connect(self.text_inserted)
        self.scene.item_selected.connect(self.item_selected)

        self.create_toolbars()

        layout = QHBoxLayout()
        layout.addWidget(self._tool_box)
        self.view = QGraphicsView(self.scene)
        layout.addWidget(self.view)

        self.widget = QWidget()
        self.widget.setLayout(layout)

        self.setCentralWidget(self.widget)
        self.statusBar()
        self.setWindowTitle("Network Topology Editor")

    @Slot(QAbstractButton)
    def background_button_group_clicked(self, button):
        buttons = self._background_button_group.buttons()
        for myButton in buttons:
            if myButton != button:
                button.setChecked(False)

        text = button.text()
        if text == "Blue Grid":
            self.scene.setBackgroundBrush(QBrush(QPixmap(':/images/background1.png')))
        elif text == "White Grid":
            self.scene.setBackgroundBrush(QBrush(QPixmap(':/images/background2.png')))
        elif text == "Gray Grid":
            self.scene.setBackgroundBrush(QBrush(QPixmap(':/images/background3.png')))
        else:
            self.scene.setBackgroundBrush(QBrush(QPixmap(':/images/background4.png')))

        self.scene.update()
        self.view.update()

    @Slot(int)
    def button_group_clicked(self, idx):
        buttons = self._button_group.buttons()
        for button in buttons:
            if self._button_group.button(idx) != button:
                button.setChecked(False)

        if idx == self.insert_text_button:
            self.scene.set_mode(DiagramScene.InsertText)
        else:
            self.scene.set_item_type(idx)
            self.scene.set_mode(DiagramScene.InsertItem)

    @Slot()
    def delete_item(self):
        for item in self.scene.selectedItems():
            if isinstance(item, (DiagramItem, DiagramImageItem)):

                if item.diagram_type == DiagramItem.Switch:
                    self.scene.available_switches.add(item.id)
                elif item.diagram_type == DiagramItem.Host:
                    self.scene.available_hosts.add(item.id)

                item.remove_arrows()
            self.scene.removeItem(item)

        print("Available Switches: ", self.scene.available_switches)
        print("Available Hosts: ", self.scene.available_hosts)
            
    @Slot(int)
    def pointer_group_clicked(self, i):
        self.scene.set_mode(self._pointer_type_group.checkedId())

    @Slot()
    def bring_to_front(self):
        if not self.scene.selectedItems():
            return

        selected_item = self.scene.selectedItems()[0]
        overlap_items = selected_item.collidingItems()

        z_value = 0
        for item in overlap_items:
            if (item.zValue() >= z_value and isinstance(item, DiagramItem)):
                z_value = item.zValue() + 0.1
        selected_item.setZValue(z_value)

    @Slot()
    def send_to_back(self):
        if not self.scene.selectedItems():
            return

        selected_item = self.scene.selectedItems()[0]
        overlap_items = selected_item.collidingItems()

        z_value = 0
        for item in overlap_items:
            if (item.zValue() <= z_value and isinstance(item, DiagramItem)):
                z_value = item.zValue() - 0.1
        selected_item.setZValue(z_value)

    @Slot(QGraphicsPolygonItem)
    def item_inserted(self, item):
        pass

    @Slot(QGraphicsTextItem)
    def text_inserted(self, item):
        self._button_group.button(self.insert_text_button).setChecked(False)
        self.scene.set_mode(self._pointer_type_group.checkedId())

    @Slot(QFont)
    def current_font_changed(self, font):
        self.handle_font_change()

    @Slot(int)
    def font_size_changed(self, font):
        self.handle_font_change()

    @Slot(str)
    def scene_scale_changed(self, scale):
        new_scale = int(scale[:-1]) / 100.0
        old_matrix = self.view.transform()
        self.view.resetTransform()
        self.view.translate(old_matrix.dx(), old_matrix.dy())
        self.view.scale(new_scale, new_scale)

    @Slot()
    def text_color_changed(self):
        self._text_action = self.sender()
        self._font_color_tool_button.setIcon(self.create_color_tool_button_icon(
            ':/images/textpointer.png', QColor(self._text_action.data())))
        self.text_button_triggered()

    @Slot()
    def item_color_changed(self):
        self._fill_action = self.sender()
        self._fill_color_tool_button.setIcon(self.create_color_tool_button_icon(
            ':/images/floodfill.png', QColor(self._fill_action.data())))
        self.fill_button_triggered()

    @Slot()
    def line_color_changed(self):
        self._line_action = self.sender()
        self._line_color_tool_button.setIcon(self.create_color_tool_button_icon(
            ':/images/linecolor.png', QColor(self._line_action.data())))
        self.line_button_triggered()

    @Slot()
    def text_button_triggered(self):
        self.scene.set_text_color(QColor(self._text_action.data()))

    @Slot()
    def fill_button_triggered(self):
        self.scene.set_item_color(QColor(self._fill_action.data()))

    @Slot()
    def line_button_triggered(self):
        self.scene.set_line_color(QColor(self._line_action.data()))

    @Slot()
    def handle_font_change(self):
        font = self._font_combo.currentFont()
        font.setPointSize(int(self._font_size_combo.currentText()))
        if self._bold_action.isChecked():
            font.setWeight(QFont.Bold)
        else:
            font.setWeight(QFont.Normal)
        font.setItalic(self._italic_action.isChecked())
        font.setUnderline(self._underline_action.isChecked())

        self.scene.set_font(font)

    @Slot(QGraphicsItem)
    def item_selected(self, item):
        font = item.font()
        self._font_combo.setCurrentFont(font)
        self._font_size_combo.setEditText(str(font.pointSize()))
        self._bold_action.setChecked(font.weight() == QFont.Weight.Bold)
        self._italic_action.setChecked(font.italic())
        self._underline_action.setChecked(font.underline())
    
    @Slot()
    def about(self):
        QMessageBox.about(self, "About Network Topology Editor",
                          "The <b>Network Topology Editor</b> shows how to easily create a network "
                          "topology and save it into a JSON file.<br><br>"
                          "Alternatively, you can load a topology from "
                          "JSON and visualize it on the canvas.<br><br>"
                          "Lastly, you can also run your current "
                          "costum topology in Mininet.")

    @Slot()
    def save(self):

        print("Save Topology Called")

        filename, _ = QFileDialog.getSaveFileName(self, "Save Topology", "", "JSON Files (*.json)")
        if not filename:
            return None
        if not filename.endswith(".json"):
            filename += ".json"
        
        connections = []
        for item in self.scene.items():
            if isinstance(item, Arrow):
                start_id = item.start_item().id
                end_id = item.end_item().id
                connections.append(sorted([start_id, end_id]))
        connections.sort()
        
        try:
            with open(filename, "w") as f:
                f.write("[\n")
                for idx, connection in enumerate(connections):
                    line = f'   {json.dumps(connection)}'
                    if idx != len(connections) - 1:
                        line += ","
                    f.write(line + "\n")
                f.write("]\n")
            QMessageBox.information(self, "Success", "Topology saved successfully!")
            return filename
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save: {e}")
            return None

    @Slot()
    def _populate_scene_from_links(self, connections: list[list[str]]):
        # 1) Clear out anything already on the scene
        self.scene.clear()

        # 2) Build a NetworkX graph from the connection pairs
        G = nx.Graph()
        for a, b in connections:
            G.add_edge(a, b)

        # 3) Compute a layout
        pos = nx.kamada_kawai_layout(G)

        # 4) Create and place each node (host or switch)
        items: dict[str, QGraphicsItem] = {}
        for node, (x, y) in pos.items():
            if node.startswith("s"):
                item = DiagramImageItem(':/images/switch.png',
                                        self._item_menu,
                                        DiagramItem.Switch)
            elif node.startswith("h"):
                item = DiagramImageItem(':/images/host.png',
                                        self._item_menu,
                                        DiagramItem.Host)
            else:
                continue

            # Give it its ID/label, add to scene, position it
            item.id = node
            item.set_label(node)
            self.scene.addItem(item)
            item.setPos(x * 500 + 2500, y * 500 + 2500)
            items[node] = item

        # 5) Draw all the arrows *behind* the icons
        for a, b in G.edges():
            start = items[a]
            end   = items[b]
            arrow = Arrow(start, end)
            arrow.set_color(self.scene._my_line_color)
            arrow.setZValue(-1000.0)
            start.add_arrow(arrow)
            end.add_arrow(arrow)
            self.scene.addItem(arrow)
            arrow.update_position()

        # 6) Finally, center & fit the view so everything is visible
        self.view.resetTransform()
        self.view.fitInView(
            self.scene.itemsBoundingRect(),
            Qt.AspectRatioMode.KeepAspectRatio
        )
                    
    @Slot()
    def load(self):

        print("Load Topology Called!")

        filename, _ = QFileDialog.getOpenFileName(self, "Load Topology", "", "JSON Files (*.json)")
        if not filename:
            return
        if not filename.endswith(".json"):
            filename += ".json"

        connections = []

        try:
            with open(filename, "r") as f:
                connections = json.load(f)

            # Clear the canvas
            self.scene.clear()

            # Step 1: Build a graph from the connections
            G = nx.Graph()
            for connection in connections:
                if len(connection) == 2:
                    G.add_edge(connection[0], connection[1])
            
            # Step 2: Compute amada-Kawai positions
            pos = nx.kamada_kawai_layout(G)

            # Step 3: Add node to the canvas
            items = {}
            for node, (x, y) in pos.items():
                if node.startswith("s"):
                    item = DiagramImageItem(':/images/switch.png', self._item_menu, DiagramItem.Switch)
                elif node.startswith("h"):
                    item = DiagramImageItem(':/images/host.png', self._item_menu, DiagramItem.Host)
                else:
                    continue

                item.id = node
                item.set_label(node)
                self.scene.addItem(item)
                item.setPos(x * 500 + 2500, y * 500 + 2500)
                items[node] = item

            # Step 4: Add edges to the canvas
            for node1, node2 in G.edges():
                start_item = items[node1]
                end_item = items[node2]
                arrow = Arrow(start_item, end_item)
                arrow.set_color(self.scene._my_line_color)
                arrow.setZValue(-1000.0) 
                start_item.add_arrow(arrow)
                end_item.add_arrow(arrow)
                self.scene.addItem(arrow)
                arrow.update_position()
                
                self.view.resetTransform()              # clear any prior zoom/pan
                self.view.fitInView(                    # fit entire scene into view
                    self.scene.itemsBoundingRect(),
                    Qt.AspectRatioMode.KeepAspectRatio
                )

            QMessageBox.information(self, "Success", "Topology loaded successfully!")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load: {e}")

    @Slot()
    def run(self):
        print("Run Topology in Mininet Called!")
	
        json_file = self.save()
        if json_file and os.path.exists(json_file):
            print(f"Running Mininet topology from {json_file}")
            #subprocess.run(["xterm", "-hold", "-e", f"sudo python3 mininet_launcher.py '{json_file}'"])
            subprocess.run(["xterm", "-e", f"sudo python3 mininet_launcher.py '{json_file}'"])
        else:
            print("Failed to save topology or file does not exist")
            QMessageBox.warning(self, "Error", "Failed to run topology!")

    def create_tool_box(self):
        # Create button groups
        self._item_button_group = QButtonGroup()
        self._item_button_group.setExclusive(True)
        
        self._text_button_group = QButtonGroup()
        self._text_button_group.setExclusive(True)

        # Create main layout
        layout = QGridLayout()

        # Create item buttons with labels
        switch_button = self.create_cell_widget("Switch", DiagramItem.Switch)
        switch_button.setStatusTip("Add Switch")
        switch_button.setToolTip("Add Switch")
        host_button = self.create_cell_widget("Host", DiagramItem.Host)
        host_button.setStatusTip("Add Host")
        host_button.setToolTip("Add Host")

        # Create switch widget with label
        switch_layout = QGridLayout()
        switch_layout.addWidget(switch_button, 0, 0, Qt.AlignmentFlag.AlignHCenter)
        switch_layout.addWidget(QLabel("Switch"), 1, 0, Qt.AlignmentFlag.AlignCenter)
        switch_widget = QWidget()
        switch_widget.setLayout(switch_layout)
        switch_widget.setStatusTip("Add Switch")
        
        # Create host widget with label
        host_layout = QGridLayout()
        host_layout.addWidget(host_button, 0, 0, Qt.AlignmentFlag.AlignHCenter)
        host_layout.addWidget(QLabel("Host"), 1, 0, Qt.AlignmentFlag.AlignCenter)
        host_widget = QWidget()
        host_widget.setLayout(host_layout)
        host_widget.setStatusTip("Add Host")

        # Add widgets to main layout with proper spacing
        layout.addWidget(switch_widget, 0, 0)
        layout.addWidget(host_widget, 0, 1)

        # Create link button
        line_pointer_button = QToolButton()
        line_pointer_button.setCheckable(True)
        line_pointer_button.setIcon(QIcon(QPixmap(':/images/linepointer.png')
                            .scaled(30, 30)))
        line_pointer_button.setIconSize(QSize(50, 50))
        line_pointer_button.setStatusTip("Create Link")
        line_pointer_button.setToolTip("Create Link")
    
        line_layout = QGridLayout()
        line_layout.addWidget(line_pointer_button, 0, 0, Qt.AlignmentFlag.AlignHCenter)
        line_layout.addWidget(QLabel("Link"), 1, 0, Qt.AlignmentFlag.AlignCenter)
        line_widget = QWidget()
        line_widget.setLayout(line_layout)
        line_widget.setStatusTip("Create Link")
        line_widget.setToolTip("Create Link")
        layout.addWidget(line_widget, 1, 0)

        self._pointer_type_group.addButton(line_pointer_button, DiagramScene.InsertLine)

        # Create text button
        text_button = QToolButton()
        text_button.setCheckable(True)
        text_button.setIcon(QIcon(QPixmap(':/images/textpointer.png')
                            .scaled(30, 30)))
        text_button.setIconSize(QSize(50, 50))
        text_button.setStatusTip("Insert Text")
        text_button.setToolTip("Insert Text")
        text_button.clicked.connect(lambda: self.scene.set_mode(DiagramScene.InsertText))

        # Create text widget with label
        text_layout = QGridLayout()
        text_layout.addWidget(text_button, 0, 0, Qt.AlignmentFlag.AlignHCenter)
        text_layout.addWidget(QLabel("Text"), 1, 0, Qt.AlignmentFlag.AlignCenter)
        text_widget = QWidget()
        text_widget.setLayout(text_layout)
        text_widget.setStatusTip("Insert Text")
        text_widget.setToolTip("Insert Text")
        layout.addWidget(text_widget, 1, 1)

        self._text_button_group.addButton(text_button, self.insert_text_button)

        # Add spacing and stretch
        layout.setRowStretch(2, 1)
        layout.setRowStretch(3, 10)
        layout.setColumnStretch(2, 10)
        
        # Add spacing between buttons
        layout.setSpacing(10)

        item_widget = QWidget()
        item_widget.setLayout(layout)

        self._background_button_group = QButtonGroup()
        self._background_button_group.buttonClicked.connect(self.background_button_group_clicked)

        background_layout = QGridLayout()
        background_layout.addWidget(
            self.create_background_cell_widget("Blue Grid", ':/images/background1.png'), 0, 0)
        background_layout.addWidget(
            self.create_background_cell_widget("White Grid", ':/images/background2.png'), 0, 1)
        background_layout.addWidget(
            self.create_background_cell_widget("Gray Grid", ':/images/background3.png'), 1, 0)
        background_layout.addWidget(
            self.create_background_cell_widget("No Grid", ':/images/background4.png'), 1, 1)

        background_layout.setRowStretch(2, 10)
        background_layout.setColumnStretch(2, 10)

        background_widget = QWidget()
        background_widget.setLayout(background_layout)

        self._tool_box = QToolBox()
        self._tool_box.setSizePolicy(QSizePolicy(QSizePolicy.Policy.Maximum,
                                     QSizePolicy.Policy.Ignored))
        self._tool_box.setMinimumWidth(item_widget.sizeHint().width())
        self._tool_box.addItem(item_widget, "Network Topology Editor")
        self._tool_box.addItem(background_widget, "Backgrounds")

    def create_actions(self):
        self._to_front_action = QAction(
            QIcon(':/images/bringtofront.png'), "Bring to &Front",
            self, shortcut="Ctrl+F", statusTip="Bring item to front",
            triggered=self.bring_to_front)

        self._send_back_action = QAction(
            QIcon(':/images/sendtoback.png'), "Send to &Back", self,
            shortcut="Ctrl+B", statusTip="Send item to back",
            triggered=self.send_to_back)

        self._delete_action = QAction(QIcon(':/images/delete.png'),
                                      "&Delete", self, shortcut="Delete",
                                      statusTip="Delete item from canvas",
                                      triggered=self.delete_item)

        self._exit_action = QAction("E&xit", self, shortcut="Ctrl+X",
                                    statusTip="Quit Network Toplogy Example", triggered=self.close)

        self._save_action = QAction("&Save", self, shortcut="Ctrl+S",
                                    statusTip="Save Current Topology", triggered=self.save)       
        
        self._load_action = QAction("&Load", self, shortcut="Ctrl+L",
                                    statusTip="Load Current Topology", triggered=self.load)
        
        self._run_action = QAction("&Run", self, shortcut="Ctrl+R",
                                   statusTip="Run in Mininet", triggered=self.run)

        self._bold_action = QAction(QIcon(':/images/bold.png'),
                                    "Bold", self, checkable=True, shortcut="Ctrl+B",
                                    triggered=self.handle_font_change)

        self._italic_action = QAction(QIcon(':/images/italic.png'),
                                      "Italic", self, checkable=True, shortcut="Ctrl+I",
                                      triggered=self.handle_font_change)

        self._underline_action = QAction(
            QIcon(':/images/underline.png'), "Underline", self,
            checkable=True, shortcut="Ctrl+U",
            triggered=self.handle_font_change)

        self._about_action = QAction("A&bout", self, shortcut="Ctrl+B", triggered=self.about)
        
        self._gen_flat_action = QAction("Generate Flat Topology…", self, #start here
            statusTip="Auto-generate a flat topology",
            triggered=self.generate_flat_topology)
        self._gen_subnet_action = QAction("Generate Subnet Topology…", self,
            statusTip="Auto-generate a subnet topology",
            triggered=self.generate_subnet_topology) #end here
        self._clear_action = QAction("Clear Canvas", self,
            shortcut="Ctrl+K",
            statusTip="Remove all items from the canvas",
            triggered=self.clear_canvas)

    def create_menus(self):
        self._file_menu = self.menuBar().addMenu("&File")
        self._file_menu.addAction(self._save_action)
        self._file_menu.addAction(self._load_action)
        self._file_menu.addAction(self._run_action)
        self._file_menu.addAction(self._clear_action)

        self._file_menu.addSeparator()
        self._file_menu.addAction(self._gen_flat_action)
        self._file_menu.addAction(self._gen_subnet_action)

        self._file_menu.addSeparator()
        self._file_menu.addAction(self._exit_action)

        self._item_menu = self.menuBar().addMenu("&Item")
        self._item_menu.addAction(self._delete_action)
        self._item_menu.addSeparator()
        self._item_menu.addAction(self._to_front_action)
        self._item_menu.addAction(self._send_back_action)

        self._about_menu = self.menuBar().addMenu("&Help")
        self._about_menu.addAction(self._about_action)
        


    @Slot()
    def generate_flat_topology(self):
        # 1) Ask the user for parameters
        hosts, ok = QInputDialog.getInt(self, "Flat Topology",
                                        "Number of hosts:", 4, 1, 100, 1)
        if not ok: return
        switches, ok = QInputDialog.getInt(self, "Flat Topology",
                                           "Number of switches:", 1, 1, 10, 1)
        if not ok: return

        # 2) Call the CLI function
        links = generate_links_flat(hosts, switches)
        # 3) Hand off to a helper that does exactly what load() does
        self._populate_scene_from_links(links)

    @Slot()
    def generate_subnet_topology(self):
        subnets, ok = QInputDialog.getInt(self, "Subnet Topology",
                                          "Number of subnets:", 2, 1, 20, 1)
        if not ok: return
        hosts_per_subnet, ok = QInputDialog.getInt(self, "Subnet Topology",
                                                   "Hosts per subnet:", 2, 1, 50, 1)
        if not ok: return
        
        links = generate_links_subnets(subnets, hosts_per_subnet)
        self._populate_scene_from_links(links)
        
    @Slot()
    def clear_canvas(self):
        # Clears everything
        self.scene.clear()
        
        # Reset host/switch counters and pools if you want fresh IDs
        self.scene.host_counter = 1
        self.scene.switch_counter = 1
        self.scene.available_hosts.clear()
        self.scene.available_switches.clear()

        # Optional: notify the user
        QMessageBox.information(self, "Canvas Cleared",
                                "All items have been removed from the canvas.")

    def create_toolbars(self):
        self._edit_tool_bar = self.addToolBar("Edit")
        self._edit_tool_bar.addAction(self._delete_action)
        self._edit_tool_bar.addAction(self._to_front_action)
        self._edit_tool_bar.addAction(self._send_back_action)

        self._font_combo = QFontComboBox()
        self._font_combo.currentFontChanged.connect(self.current_font_changed)

        self._font_size_combo = QComboBox()
        self._font_size_combo.setEditable(True)
        for i in range(8, 30, 2):
            self._font_size_combo.addItem(str(i))
        validator = QIntValidator(2, 64, self)
        self._font_size_combo.setValidator(validator)
        self._font_size_combo.currentIndexChanged.connect(self.font_size_changed)

        self._font_color_tool_button = QToolButton()
        self._font_color_tool_button.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        self._font_color_tool_button.setMenu(
            self.create_color_menu(self.text_color_changed, Qt.GlobalColor.black))
        self._text_action = self._font_color_tool_button.menu().defaultAction()
        self._font_color_tool_button.setIcon(
            self.create_color_tool_button_icon(':/images/textpointer.png', Qt.GlobalColor.black))
        self._font_color_tool_button.setAutoFillBackground(True)
        self._font_color_tool_button.clicked.connect(self.text_button_triggered)

        self._fill_color_tool_button = QToolButton()
        self._fill_color_tool_button.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        self._fill_color_tool_button.setMenu(
            self.create_color_menu(self.item_color_changed, Qt.GlobalColor.white))
        self._fill_action = self._fill_color_tool_button.menu().defaultAction()
        self._fill_color_tool_button.setIcon(
            self.create_color_tool_button_icon(':/images/floodfill.png', Qt.GlobalColor.white))
        self._fill_color_tool_button.clicked.connect(self.fill_button_triggered)

        self._line_color_tool_button = QToolButton()
        self._line_color_tool_button.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        self._line_color_tool_button.setMenu(
            self.create_color_menu(self.line_color_changed, Qt.GlobalColor.black))
        self._line_action = self._line_color_tool_button.menu().defaultAction()
        self._line_color_tool_button.setIcon(
            self.create_color_tool_button_icon(':/images/linecolor.png', Qt.GlobalColor.black))
        self._line_color_tool_button.clicked.connect(self.line_button_triggered)

        self._text_tool_bar = self.addToolBar("Font")
        self._text_tool_bar.addWidget(self._font_combo)
        self._text_tool_bar.addWidget(self._font_size_combo)
        self._text_tool_bar.addAction(self._bold_action)
        self._text_tool_bar.addAction(self._italic_action)
        self._text_tool_bar.addAction(self._underline_action)

        self._color_tool_bar = self.addToolBar("Color")
        self._color_tool_bar.addWidget(self._font_color_tool_button)
        self._color_tool_bar.addWidget(self._fill_color_tool_button)
        self._color_tool_bar.addWidget(self._line_color_tool_button)

        pointer_button = QToolButton()
        pointer_button.setCheckable(True)
        pointer_button.setChecked(True)
        pointer_button.setIcon(QIcon(':/images/pointer.png'))
        pointer_button.setIconSize(QSize(30, 30))
        pointer_button.setStatusTip("Move Items")
        pointer_button.setToolTip("Move Items")
        line_pointer_button = QToolButton()
        line_pointer_button.setCheckable(True)
        line_pointer_button.setIcon(QIcon(':/images/linepointer.png'))
        line_pointer_button.setStatusTip("Create Link")
        line_pointer_button.setToolTip("Create Link")

        # Add toolbar buttons to the existing pointer type group
        self._pointer_type_group.addButton(pointer_button, DiagramScene.MoveItem)
        self._pointer_type_group.addButton(line_pointer_button, DiagramScene.InsertLine)

        self._scene_scale_combo = QComboBox()
        self._scene_scale_combo.addItems(["50%", "75%", "100%", "125%", "150%"])
        self._scene_scale_combo.setCurrentIndex(2)
        self._scene_scale_combo.currentTextChanged.connect(self.scene_scale_changed)

        self._pointer_toolbar = self.addToolBar("Pointer type")
        self._pointer_toolbar.addWidget(pointer_button)
        self._pointer_toolbar.addWidget(line_pointer_button)
        self._pointer_toolbar.addWidget(self._scene_scale_combo)

    def create_background_cell_widget(self, text, image):
        button = QToolButton()
        button.setText(text)
        button.setIcon(QIcon(image))
        button.setIconSize(QSize(50, 50))
        button.setCheckable(True)
        self._background_button_group.addButton(button)

        layout = QGridLayout()
        layout.addWidget(button, 0, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(QLabel(text), 1, 0, Qt.AlignmentFlag.AlignCenter)

        widget = QWidget()
        widget.setLayout(layout)

        return widget

    def create_cell_widget(self, text, diagram_type):
        if diagram_type == DiagramItem.Switch:
            icon = QIcon(':/images/switch.png') # Switch image
        elif diagram_type == DiagramItem.Host: 
            icon = QIcon(':/images/host.png') # Host
        else:
            item = DiagramItem(diagram_type, self._item_menu)
            icon = QIcon(item.image())

        button = QToolButton()
        button.setIcon(icon)
        button.setIconSize(QSize(50, 50))
        button.setCheckable(True)
        button.clicked.connect(lambda: self.scene.set_mode(DiagramScene.InsertItem))
        button.clicked.connect(lambda: self.scene.set_item_type(diagram_type))
        self._item_button_group.addButton(button, diagram_type)
        
        return button

        layout = QGridLayout()
        layout.addWidget(button, 0, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(QLabel(text), 1, 0, Qt.AlignmentFlag.AlignCenter)

        widget = QWidget()
        widget.setLayout(layout)

        return widget

    def create_color_menu(self, slot, defaultColor):
        colors = [Qt.GlobalColor.black, Qt.GlobalColor.white, Qt.GlobalColor.red,
                  Qt.GlobalColor.blue, Qt.GlobalColor.yellow]
        names = ["black", "white", "red", "blue", "yellow"]

        color_menu = QMenu(self)
        for color, name in zip(colors, names):
            action = QAction(self.create_color_icon(color), name, self, triggered=slot)
            action.setData(QColor(color))
            color_menu.addAction(action)
            if color == defaultColor:
                color_menu.setDefaultAction(action)
        return color_menu

    def create_color_tool_button_icon(self, imageFile, color):
        pixmap = QPixmap(50, 80)
        pixmap.fill(Qt.GlobalColor.transparent)

        with QPainter(pixmap) as painter:
            image = QPixmap(imageFile)
            target = QRect(0, 0, 50, 60)
            source = QRect(0, 0, 42, 42)
            painter.fillRect(QRect(0, 60, 50, 80), color)
            painter.drawPixmap(target, image, source)

        return QIcon(pixmap)

    def create_color_icon(self, color):
        pixmap = QPixmap(20, 20)

        with QPainter(pixmap) as painter:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.fillRect(QRect(0, 0, 20, 20), color)

        return QIcon(pixmap)
    
    

if __name__ == '__main__':
    app = QApplication(sys.argv)

    main_window = MainWindow()
    main_window.setWindowIcon(QIcon(':/images/network.png'))
    main_window.setGeometry(100, 100, 1000, 700)
    main_window.show()

    sys.exit(app.exec())

