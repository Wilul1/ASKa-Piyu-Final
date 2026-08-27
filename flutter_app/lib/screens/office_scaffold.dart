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

  const OfficeScaffold({
    super.key,
    required this.current,
    required this.title,
    required this.description,
    required this.child,
    this.actions,
    this.fillBody = false,
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
                Padding(
                  padding: EdgeInsets.fromLTRB(
                    isWide ? 20 : 14,
                    isWide ? 16 : 12,
                    isWide ? 20 : 14,
                    10,
                  ),
                  child: Row(
                    children: [
                      Expanded(
                        child: Column(
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
                      ),
                      if (actions != null) ...actions!,
                    ],
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
                    Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Expanded(
                          child: Column(
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
                        ),
                        if (actions != null) ...actions!,
                      ],
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
