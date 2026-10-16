import 'package:flutter/material.dart';

import '../auth/auth_state.dart';
import '../design_tokens.dart';
import '../widgets/sidebar.dart';
import '../widgets/student_ui.dart';
import 'login_page.dart';

/// Shared chrome for office staff pages (maroon sidebar + clean content header).
class OfficeScaffold extends StatelessWidget {
  final StudentNavItem current;
  final String title;
  final String description;
  final Widget child;
  final List<Widget>? actions;
  final bool fillBody;
  final bool showHeader;

  const OfficeScaffold({
    super.key,
    required this.current,
    required this.title,
    required this.description,
    required this.child,
    this.actions,
    this.fillBody = false,
    this.showHeader = true,
  });

  @override
  Widget build(BuildContext context) {
    final auth = AuthScope.of(context);
    if (auth.role != 'office') {
      return Scaffold(
        backgroundColor: DesignTokens.adminSurface,
        appBar: AppBar(title: Text(title)),
        body: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 460),
            child: StudentPanel(
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  const StudentSectionTitle(
                    title: 'Office access required',
                    subtitle:
                        'Please log in with an office account to open this page.',
                  ),
                  const SizedBox(height: 16),
                  ElevatedButton(
                    onPressed: () => Navigator.of(context).push(
                      MaterialPageRoute(
                        builder: (_) => LoginPage(
                          returnTo: (_) => this,
                          message:
                              'Please log in with an office account to open office tools.',
                        ),
                      ),
                    ),
                    child: const Text('Login'),
                  ),
                ],
              ),
            ),
          ),
        ),
      );
    }

    return LayoutBuilder(
      builder: (context, constraints) {
        final isWide = constraints.maxWidth >= 900;
        final Widget content;
        if (fillBody) {
          content = ColoredBox(
            color: DesignTokens.adminSurface,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                if (showHeader)
                  Padding(
                    padding: EdgeInsets.fromLTRB(
                      isWide ? 20 : 14,
                      isWide ? 16 : 12,
                      isWide ? 20 : 14,
                      10,
                    ),
                    child: _ResponsiveHeader(
                      titleColumn: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            title,
                            style: const TextStyle(
                              color: DesignTokens.ink,
                              fontSize: 22,
                              fontWeight: FontWeight.w900,
                            ),
                          ),
                          const SizedBox(height: 4),
                          Text(
                            description,
                            style: const TextStyle(
                              color: DesignTokens.muted,
                              fontSize: 13,
                              fontWeight: FontWeight.w600,
                            ),
                          ),
                        ],
                      ),
                      actions: actions,
                    ),
                  ),
                Expanded(child: child),
              ],
            ),
          );
        } else {
          content = ColoredBox(
            color: DesignTokens.adminSurface,
            child: Align(
              alignment: Alignment.topCenter,
              child: ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 1240),
                child: ListView(
                  padding: EdgeInsets.fromLTRB(
                    isWide ? 28 : 18,
                    isWide ? 28 : 16,
                    isWide ? 28 : 18,
                    32,
                  ),
                  children: [
                    _ResponsiveHeader(
                      titleColumn: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            title,
                            style: const TextStyle(
                              color: DesignTokens.ink,
                              fontSize: 26,
                              fontWeight: FontWeight.w900,
                              height: 1.15,
                            ),
                          ),
                          const SizedBox(height: 6),
                          Text(
                            description,
                            style: const TextStyle(
                              color: DesignTokens.muted,
                              fontSize: 14,
                              fontWeight: FontWeight.w600,
                              height: 1.35,
                            ),
                          ),
                        ],
                      ),
                      actions: actions,
                    ),
                    const SizedBox(height: 22),
                    child,
                  ],
                ),
              ),
            ),
          );
        }

        if (isWide) {
          return Scaffold(
            backgroundColor: DesignTokens.adminSurface,
            body: Row(
              children: [
                SizedBox(
                  width: DesignTokens.adminSidebarWidth,
                  child: AppSidebar(current: current),
                ),
                Expanded(child: content),
              ],
            ),
          );
        }

        return Scaffold(
          backgroundColor: DesignTokens.adminSurface,
          drawer: Drawer(
            backgroundColor: DesignTokens.adminSidebarBg,
            child: AppSidebar(current: current),
          ),
          appBar: AppBar(
            title: Text(title),
            backgroundColor: Colors.white,
            foregroundColor: DesignTokens.ink,
            elevation: 0,
            scrolledUnderElevation: 0.5,
          ),
          body: content,
        );
      },
    );
  }
}

/// The title/description + page actions, shared by both of OfficeScaffold's
/// header occurrences (fillBody and the default ListView layout). Row
/// children in Flutter's Flex layout give *inflexible* siblings (the raw
/// `...actions!` this replaces) unbounded main-axis space to report their
/// own size -- so a plain Row, or even a bare Wrap/OverflowBar placed as
/// one of its non-flex children, never actually triggers wrapping no
/// matter how little room is left; it just overflows. The only way to
/// give the actions a genuinely bounded width to react to is to measure
/// the real available width directly (via LayoutBuilder) and switch
/// layouts outright once title + actions together don't comfortably fit
/// on one line.
class _ResponsiveHeader extends StatelessWidget {
  const _ResponsiveHeader({required this.titleColumn, required this.actions});

  final Widget titleColumn;
  final List<Widget>? actions;

  /// Confirmed by direct measurement (a two-action header's RenderFlex
  /// reported needing ~612-620px to avoid overflowing, across every
  /// width from 360 to 900) -- this sits comfortably above that with
  /// margin for a somewhat longer label, while still correctly catching
  /// every width in that confirmed-overflowing range.
  static const double _wrapBreakpoint = 700;

  @override
  Widget build(BuildContext context) {
    final hasActions = actions != null && actions!.isNotEmpty;
    if (!hasActions) {
      // Nothing to ever compete with the title column for space, so this
      // never needs the width check below -- unchanged from before.
      return Row(children: [Expanded(child: titleColumn)]);
    }
    return LayoutBuilder(
      builder: (context, constraints) {
        if (constraints.maxWidth >= _wrapBreakpoint) {
          // Enough room: the exact original Row, unchanged -- zero
          // visual difference from before on wider screens.
          return Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Expanded(child: titleColumn),
              ...actions!,
            ],
          );
        }
        // Not enough room for the title and every action on one line.
        // Title/description keep the full line to themselves (still
        // fully readable, never clipped); the actions move below in a
        // Wrap, so they stay visible, reachable, and non-overlapping --
        // flowing onto further lines of their own if there isn't even
        // room for all of them side by side.
        return Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            titleColumn,
            const SizedBox(height: 10),
            Wrap(spacing: 8, runSpacing: 8, children: actions!),
          ],
        );
      },
    );
  }
}
