import 'dart:math' as math;

import 'package:flutter/material.dart';

/// Dialog body that keeps a desktop preferred width, but never wider than the
/// phone viewport. Content scrolls; dialog actions stay outside this widget.
///
/// Does not use [LayoutBuilder]. [AlertDialog] measures intrinsic size, and a
/// [LayoutBuilder] cannot answer that.
class ResponsiveDialogBody extends StatelessWidget {
  const ResponsiveDialogBody({
    super.key,
    required this.maxWidth,
    required this.child,
  });

  final double maxWidth;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    final media = MediaQuery.of(context);
    final fitted = math.max(120.0, media.size.width - 160);
    final width = math.min(maxWidth, fitted);
    final availableHeight = math.max(
      96.0,
      media.size.height - media.viewInsets.bottom - 176,
    );
    return SizedBox(
      width: width,
      child: ConstrainedBox(
        constraints: BoxConstraints(maxHeight: availableHeight),
        child: SingleChildScrollView(child: child),
      ),
    );
  }
}
