import 'dart:async';
import 'dart:html' as html;
import 'dart:js_util' as js_util;
import 'dart:math' as math;

import 'package:flutter/material.dart';

final Set<VoidCallback> _listeners = <VoidCallback>{};
bool _domBound = false;
double _vkHeight = 0;
Timer? _poll;
double _lastReportedInset = 0;

void bindVisualViewportListener(VoidCallback onChange) {
  _listeners.add(onChange);
  _ensureDomListeners();
  _ensureVirtualKeyboard();
  _ensurePoll();
}

void unbindVisualViewportListener(VoidCallback onChange) {
  _listeners.remove(onChange);
  if (_listeners.isEmpty) {
    _poll?.cancel();
    _poll = null;
  }
}

void _notify() {
  for (final listener in List<VoidCallback>.from(_listeners)) {
    listener();
  }
}

void _ensurePoll() {
  _poll?.cancel();
  _poll = Timer.periodic(const Duration(milliseconds: 120), (_) {
    _readVk();
    final next = extraVisualViewportInset();
    if ((next - _lastReportedInset).abs() >= 1) {
      _lastReportedInset = next;
      _notify();
    }
  });
}

void _ensureDomListeners() {
  if (_domBound) return;
  _domBound = true;
  void fire(html.Event _) => _notify();
  html.window.visualViewport?.addEventListener('resize', fire);
  html.window.visualViewport?.addEventListener('scroll', fire);
  html.window.addEventListener('resize', fire);
}

void _ensureVirtualKeyboard() {
  try {
    final vk = js_util.getProperty(html.window.navigator, 'virtualKeyboard');
    if (vk == null) return;
    js_util.setProperty(vk, 'overlaysContent', true);
    js_util.callMethod(vk, 'addEventListener', [
      'geometrychange',
      js_util.allowInterop((dynamic _) {
        _readVk();
        _notify();
      }),
    ]);
    _readVk();
  } catch (_) {}
}

void _readVk() {
  try {
    final vk = js_util.getProperty(html.window.navigator, 'virtualKeyboard');
    if (vk == null) return;
    final rect = js_util.getProperty(vk, 'boundingRect');
    _vkHeight = (js_util.getProperty(rect, 'height') as num).toDouble();
  } catch (_) {
    _vkHeight = 0;
  }
}

/// Only real keyboard overlap. Never guess from focus — that left a hole
/// after the keyboard closed and hid the chat greeting / login form.
double extraVisualViewportInset({bool textFocused = false}) {
  final viewport = html.window.visualViewport;
  final vvHeight = (viewport?.height ?? html.window.innerHeight ?? 0).toDouble();
  final offsetTop = (viewport?.offsetTop ?? 0).toDouble();
  final inner = (html.window.innerHeight ?? 0).toDouble();
  final clientH =
      (html.document.documentElement?.clientHeight ?? 0).toDouble();

  final fromInner = inner - vvHeight - offsetTop;
  final fromClient = clientH - vvHeight - offsetTop;
  var real = math.max(_vkHeight, 0.0);
  if (fromInner > real) real = fromInner;
  if (fromClient > real) real = fromClient;
  if (real.isNaN || real.isInfinite || real < 80) return 0;
  return real;
}
