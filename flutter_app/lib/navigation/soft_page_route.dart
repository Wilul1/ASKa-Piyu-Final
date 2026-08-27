import 'package:flutter/material.dart';

/// Soft fade + slight slide used for public page changes.
class SoftFadePageTransitionsBuilder extends PageTransitionsBuilder {
  const SoftFadePageTransitionsBuilder();

  @override
  Widget buildTransitions<T>(
    PageRoute<T> route,
    BuildContext context,
    Animation<double> animation,
    Animation<double> secondaryAnimation,
    Widget child,
  ) {
    return buildSoftPageTransitions(
      animation,
      secondaryAnimation,
      child,
    );
  }
}

Widget buildSoftPageTransitions(
  Animation<double> animation,
  Animation<double> secondaryAnimation,
  Widget child,
) {
  final enter = CurvedAnimation(
    parent: animation,
    curve: Curves.easeOutCubic,
    reverseCurve: Curves.easeInCubic,
  );
  final exit = CurvedAnimation(
    parent: secondaryAnimation,
    curve: Curves.easeOutCubic,
  );

  return FadeTransition(
    opacity: Tween<double>(begin: 1, end: 0.88).animate(exit),
    child: SlideTransition(
      position: Tween<Offset>(
        begin: Offset.zero,
        end: const Offset(-0.012, 0),
      ).animate(exit),
      child: FadeTransition(
        opacity: enter,
        child: SlideTransition(
          position: Tween<Offset>(
            begin: const Offset(0.018, 0.01),
            end: Offset.zero,
          ).animate(enter),
          child: child,
        ),
      ),
    ),
  );
}

/// Applies [SoftFadePageTransitionsBuilder] on every platform (including web).
const PageTransitionsTheme softPageTransitionsTheme = PageTransitionsTheme(
  builders: {
    TargetPlatform.android: SoftFadePageTransitionsBuilder(),
    TargetPlatform.iOS: SoftFadePageTransitionsBuilder(),
    TargetPlatform.macOS: SoftFadePageTransitionsBuilder(),
    TargetPlatform.windows: SoftFadePageTransitionsBuilder(),
    TargetPlatform.linux: SoftFadePageTransitionsBuilder(),
    TargetPlatform.fuchsia: SoftFadePageTransitionsBuilder(),
  },
);

/// Page route with a slightly longer, softer transition than stock Material.
class SoftPageRoute<T> extends PageRouteBuilder<T> {
  SoftPageRoute({
    required WidgetBuilder builder,
    super.settings,
    super.fullscreenDialog,
  }) : super(
          transitionDuration: const Duration(milliseconds: 340),
          reverseTransitionDuration: const Duration(milliseconds: 280),
          pageBuilder: (context, animation, secondaryAnimation) =>
              builder(context),
          transitionsBuilder: (context, animation, secondaryAnimation, child) =>
              buildSoftPageTransitions(animation, secondaryAnimation, child),
        );
}

Future<T?> softPush<T extends Object?>(
  BuildContext context,
  Widget page, {
  bool rootNavigator = false,
}) {
  return Navigator.of(context, rootNavigator: rootNavigator).push<T>(
    SoftPageRoute<T>(builder: (_) => page),
  );
}

Future<T?> softReplace<T extends Object?>(
  BuildContext context,
  Widget page, {
  bool rootNavigator = false,
}) {
  return Navigator.of(context, rootNavigator: rootNavigator)
      .pushReplacement<T, T>(
    SoftPageRoute<T>(builder: (_) => page),
  );
}

Future<T?> softPushAndClear<T extends Object?>(
  BuildContext context,
  Widget page,
) {
  return Navigator.of(context).pushAndRemoveUntil<T>(
    SoftPageRoute<T>(builder: (_) => page),
    (_) => false,
  );
}
