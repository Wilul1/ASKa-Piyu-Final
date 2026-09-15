import 'package:flutter/material.dart';

import '../services/file_pick.dart';

class ArticleFileDropHost extends StatelessWidget {
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
  Widget build(BuildContext context) => child;
}
