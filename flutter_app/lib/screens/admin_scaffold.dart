import 'package:flutter/material.dart';

import '../auth/auth_state.dart';
import '../design_tokens.dart';
import '../widgets/sidebar.dart';
import '../widgets/student_ui.dart';
import 'login_page.dart';

class AdminScaffold extends StatelessWidget {
  final StudentNavItem current;
  final String title;
  final String description;
  final Widget child;

  const AdminScaffold({
    super.key,
    required this.current,
    required this.title,
    required this.description,
    required this.child,
  });

  @override
  Widget build(BuildContext context) {
    final auth = AuthScope.of(context);
    if (auth.role != 'admin') {
      return Scaffold(
        backgroundColor: DesignTokens.bgGrey,
        appBar: AppBar(title: Text(title)),
        body: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 460),
            child: StudentPanel(
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  const StudentIconBox(
                    icon: Icons.admin_panel_settings_rounded,
                    color: DesignTokens.maroon,
                    size: 52,
                  ),
                  const SizedBox(height: 14),
                  const StudentSectionTitle(
                    title: 'Admin access required',
                    subtitle:
                        'Please log in with an admin account to open this page.',
                  ),
                  const SizedBox(height: 16),
                  ElevatedButton(
                    onPressed: () => Navigator.of(context).push(
                      MaterialPageRoute(
                        builder: (_) => LoginPage(
                          returnTo: (_) => this,
                          message:
                              'Please log in with an admin account to open admin tools.',
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
        final content = StudentPage(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              StudentPanel(
                child: Row(
                  children: [
                    const StudentIconBox(
                      icon: Icons.admin_panel_settings_rounded,
                      color: DesignTokens.maroon,
                      size: 52,
                    ),
                    const SizedBox(width: 14),
                    Expanded(
                      child: StudentSectionTitle(
                        title: title,
                        subtitle: description,
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 18),
              child,
            ],
          ),
        );

        if (isWide) {
          return Scaffold(
            backgroundColor: DesignTokens.bgGrey,
            body: Row(
              children: [
                SizedBox(width: 220, child: AppSidebar(current: current)),
                Expanded(child: content),
              ],
            ),
          );
        }

        return Scaffold(
          backgroundColor: DesignTokens.bgGrey,
          drawer: Drawer(child: AppSidebar(current: current)),
          appBar: AppBar(title: Text(title)),
          body: content,
        );
      },
    );
  }
}
