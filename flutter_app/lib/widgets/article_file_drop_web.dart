import 'dart:async';
import 'dart:html' as html;
import 'dart:typed_data';
import 'dart:ui_web' as ui_web;

import 'package:flutter/material.dart';

import '../services/file_pick.dart';

class ArticleFileDropHost extends StatefulWidget {
  const ArticleFileDropHost({
    super.key,
    required this.child,
    required this.onDropped,
    this.enabled = true,
    this.hovering = false,
    this.onHoverChanged,
  });

  final Widget child;
  final ValueChanged<List<PickedAppFile>> onDropped;
  final bool enabled;
  final bool hovering;
  final ValueChanged<bool>? onHoverChanged;

  @override
  State<ArticleFileDropHost> createState() => _ArticleFileDropHostState();
}

class _ArticleFileDropHostState extends State<ArticleFileDropHost> {
  late final String _viewType;
  late final html.DivElement _element;
  StreamSubscription<html.MouseEvent>? _over;
  StreamSubscription<html.MouseEvent>? _leave;
  StreamSubscription<html.MouseEvent>? _drop;

  @override
  void initState() {
    super.initState();
    _viewType = 'aska-article-drop-${identityHashCode(this)}';
    _element = html.DivElement()
      ..style.width = '100%'
      ..style.height = '100%'
      ..style.position = 'absolute'
      ..style.left = '0'
      ..style.top = '0'
      ..style.pointerEvents = 'none';
    ui_web.platformViewRegistry.registerViewFactory(
      _viewType,
      (int viewId) => _element,
    );
    html.document.body?.addEventListener('dragenter', _enableOverlay);
    _over = _element.onDragOver.listen((event) {
      event.preventDefault();
      widget.onHoverChanged?.call(true);
    });
    _leave = _element.onDragLeave.listen((event) {
      widget.onHoverChanged?.call(false);
      _element.style.pointerEvents = 'none';
    });
    _drop = _element.onDrop.listen((event) async {
      event.preventDefault();
      widget.onHoverChanged?.call(false);
      _element.style.pointerEvents = 'none';
      if (!widget.enabled) return;
      final transfer = event.dataTransfer;
      if (transfer == null) return;
      final files = <PickedAppFile>[];
      for (final file in transfer.files ?? const <html.File>[]) {
        final reader = html.FileReader();
        final done = Completer<void>();
        reader.onLoad.listen((_) {
          final result = reader.result;
          if (result is List<int>) {
            files.add(
              PickedAppFile(name: file.name, bytes: Uint8List.fromList(result)),
            );
          } else if (result is Uint8List) {
            files.add(PickedAppFile(name: file.name, bytes: result));
          } else if (result is ByteBuffer) {
            files.add(
              PickedAppFile(name: file.name, bytes: result.asUint8List()),
            );
          }
          done.complete();
        });
        reader.onError.listen((_) => done.complete());
        reader.readAsArrayBuffer(file);
        await done.future;
      }
      if (files.isNotEmpty) widget.onDropped(files);
    });
  }

  void _enableOverlay(html.Event event) {
    if (!widget.enabled) return;
    final mouse = event is html.MouseEvent ? event : null;
    final types = mouse?.dataTransfer?.types ?? const [];
    if (types.contains('Files')) {
      _element.style.pointerEvents = 'auto';
    }
  }

  @override
  void dispose() {
    html.document.body?.removeEventListener('dragenter', _enableOverlay);
    _over?.cancel();
    _leave?.cancel();
    _drop?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Stack(
      children: [
        widget.child,
        Positioned.fill(
          child: HtmlElementView(viewType: _viewType),
        ),
      ],
    );
  }
}
