import 'package:flutter/material.dart';

import 'phone_keyboard_inset.dart';

/// Public-site phone layout (matches [PublicSiteHeader] narrow breakpoint).
const double kPhoneLayoutBreakpoint = 880;

bool isPhoneLayout(BuildContext context) =>
    MediaQuery.sizeOf(context).width < kPhoneLayoutBreakpoint;

double phoneKeyboardInset(BuildContext context) {
  final fromMedia = MediaQuery.viewInsetsOf(context).bottom;
  final view = View.of(context);
  final fromView = view.viewInsets.bottom / view.devicePixelRatio;
  final node = FocusManager.instance.primaryFocus;
  var textFocused = false;
  if (node != null && node.hasFocus) {
    final focusContext = node.context;
    if (focusContext != null) {
      textFocused = focusContext.widget is EditableText ||
          focusContext.findAncestorWidgetOfExactType<EditableText>() != null ||
          focusContext.findAncestorWidgetOfExactType<TextField>() != null ||
          focusContext.findAncestorWidgetOfExactType<TextFormField>() != null;
    }
  }
  final fromViewport = extraVisualViewportInset(textFocused: textFocused);
  var inset = fromMedia;
  if (fromView > inset) inset = fromView;
  if (fromViewport > inset) inset = fromViewport;
  return inset;
}
