"""Blender-like VTK interactor style.

Port of arc-c++/src/render/vtk/vtk_render_backend.cpp:28-129.
LMB = select, Alt+LMB = rotate, MMB = rotate, Shift+MMB = pan,
Ctrl+MMB / RMB = dolly. OnChar() is empty to suppress VTK defaults.
"""

from vtkmodules.vtkInteractionStyle import vtkInteractorStyleTrackballCamera
from vtkmodules.vtkRenderingCore import vtkRenderWindowInteractor


VTKIS_ROTATE = 1
VTKIS_PAN = 2
VTKIS_DOLLY = 4


class BlenderLikeInteractorStyle(vtkInteractorStyleTrackballCamera):

    def __init__(self):
        super().__init__()
        self._left_alt_rotate_active = False

    def OnChar(self):
        # Disable VTK default char bindings (notably w/s representation toggles).
        pass

    def OnLeftButtonDown(self):
        interactor: vtkRenderWindowInteractor | None = self.GetInteractor()
        if interactor is None:
            return

        if interactor.GetAltKey():
            pos = interactor.GetEventPosition()
            self.FindPokedRenderer(pos[0], pos[1])
            if self.GetCurrentRenderer() is None:
                return
            self.GrabFocus(self.GetEventCallbackCommand())
            self.StartRotate()
            self._left_alt_rotate_active = True
            return
        # LMB without Alt = selection (handled by pick callback in backend)

    def OnLeftButtonUp(self):
        if not self._left_alt_rotate_active:
            return
        self.EndRotate()
        self._left_alt_rotate_active = False
        if self.GetInteractor() is not None:
            self.ReleaseFocus()

    def OnMiddleButtonDown(self):
        interactor = self.GetInteractor()
        if interactor is None:
            return

        pos = interactor.GetEventPosition()
        self.FindPokedRenderer(pos[0], pos[1])
        if self.GetCurrentRenderer() is None:
            return

        self.GrabFocus(self.GetEventCallbackCommand())
        if interactor.GetControlKey():
            self.StartDolly()
        elif interactor.GetShiftKey():
            self.StartPan()
        else:
            self.StartRotate()

    def OnMiddleButtonUp(self):
        state = self.GetState()
        if state == VTKIS_ROTATE:
            self.EndRotate()
        elif state == VTKIS_PAN:
            self.EndPan()
        elif state == VTKIS_DOLLY:
            self.EndDolly()
        if self.GetInteractor() is not None:
            self.ReleaseFocus()

    def OnRightButtonDown(self):
        interactor = self.GetInteractor()
        if interactor is None:
            return
        pos = interactor.GetEventPosition()
        self.FindPokedRenderer(pos[0], pos[1])
        if self.GetCurrentRenderer() is None:
            return
        self.GrabFocus(self.GetEventCallbackCommand())
        self.StartDolly()

    def OnRightButtonUp(self):
        if self.GetState() == VTKIS_DOLLY:
            self.EndDolly()
        if self.GetInteractor() is not None:
            self.ReleaseFocus()
