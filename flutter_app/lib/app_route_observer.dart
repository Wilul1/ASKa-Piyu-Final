import 'package:flutter/material.dart';

/// Shared observer so pages can refresh when the user navigates back to them.
final RouteObserver<ModalRoute<void>> appRouteObserver =
    RouteObserver<ModalRoute<void>>();
