import 'package:flutter/material.dart';

import '../auth/auth_navigation.dart';
import '../auth/auth_state.dart';
import '../design_tokens.dart';
import '../models/auth_models.dart';
import '../widgets/public_site_header.dart';

/// Account settings: slim left nav (Account only) + row-based account panel.
class SettingsPage extends StatelessWidget {
  const SettingsPage({super.key});

  @override
  Widget build(BuildContext context) {
    final auth = AuthScope.of(context);
    final user = auth.currentUser;
    final width = MediaQuery.sizeOf(context).width;
    final showNav = width >= 760;

    return Scaffold(
      backgroundColor: const Color(0xFFF3F4F6),
      body: Column(
        children: [
          const PublicSiteHeader(accountActive: true),
          Expanded(
            child: Center(
              child: ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 980),
                child: Padding(
                  padding: EdgeInsets.fromLTRB(
                    showNav ? 20 : 16,
                    24,
                    showNav ? 20 : 16,
                    32,
                  ),
                  child: user == null
                      ? const _SettingsSignedOut()
                      : DecoratedBox(
                          decoration: BoxDecoration(
                            color: Colors.white,
                            borderRadius: BorderRadius.circular(18),
                            border: Border.all(color: DesignTokens.border),
                            boxShadow: DesignTokens.softShadow(0.04),
                          ),
                          child: ClipRRect(
                            borderRadius: BorderRadius.circular(18),
                            child: Row(
                              crossAxisAlignment: CrossAxisAlignment.stretch,
                              children: [
                                if (showNav) const _SettingsSideNav(),
                                Expanded(
                                  child: _AccountPanel(
                                    user: user,
                                    onChangePassword: () =>
                                        _showChangePasswordDialog(context),
                                    onSignOut: () => signOutToHome(context),
                                  ),
                                ),
                              ],
                            ),
                          ),
                        ),
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }

  static String roleLabel(String role) {
    final normalized = role.trim().toLowerCase();
    switch (normalized) {
      case 'faculty':
        return 'Faculty';
      case 'student':
        return 'Student';
      case 'office':
        return 'Office staff';
      case 'admin':
        return 'Administrator';
      default:
        return role.trim().isEmpty ? 'User' : role.trim();
    }
  }

  Future<void> _showChangePasswordDialog(BuildContext context) async {
    final changed = await showDialog<bool>(
      context: context,
      builder: (_) => const _ChangePasswordDialog(),
    );
    if (changed == true && context.mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Password updated.')),
      );
    }
  }
}

class _SettingsSideNav extends StatelessWidget {
  const _SettingsSideNav();

  @override
  Widget build(BuildContext context) {
    return Container(
      width: 220,
      decoration: const BoxDecoration(
        color: Color(0xFFFAFAFA),
        border: Border(right: BorderSide(color: DesignTokens.border)),
      ),
      child: SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(12, 18, 12, 18),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              const Padding(
                padding: EdgeInsets.fromLTRB(10, 0, 10, 14),
                child: Text(
                  'Settings',
                  style: TextStyle(
                    fontWeight: FontWeight.w800,
                    fontSize: 13,
                    color: DesignTokens.muted,
                    letterSpacing: 0.2,
                  ),
                ),
              ),
              Material(
                color: DesignTokens.maroon.withValues(alpha: 0.08),
                borderRadius: BorderRadius.circular(12),
                child: InkWell(
                  borderRadius: BorderRadius.circular(12),
                  onTap: () {},
                  child: const Padding(
                    padding: EdgeInsets.symmetric(horizontal: 12, vertical: 12),
                    child: Row(
                      children: [
                        Icon(
                          Icons.person_outline_rounded,
                          size: 20,
                          color: DesignTokens.maroon,
                        ),
                        SizedBox(width: 10),
                        Text(
                          'Account',
                          style: TextStyle(
                            fontWeight: FontWeight.w800,
                            fontSize: 14,
                            color: DesignTokens.maroon,
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _AccountPanel extends StatelessWidget {
  final AuthUser user;
  final VoidCallback onChangePassword;
  final Future<void> Function() onSignOut;

  const _AccountPanel({
    required this.user,
    required this.onChangePassword,
    required this.onSignOut,
  });

  @override
  Widget build(BuildContext context) {
    final isFaculty = user.role.trim().toLowerCase() == 'faculty';
    final office = (user.officeName ?? '').trim();

    return ListView(
      padding: const EdgeInsets.fromLTRB(28, 28, 28, 36),
      children: [
        const Text(
          'Account',
          style: TextStyle(
            fontSize: 28,
            fontWeight: FontWeight.w900,
            color: DesignTokens.ink,
            height: 1.15,
          ),
        ),
        const SizedBox(height: 8),
        Text(
          isFaculty
              ? 'Your faculty login for ASKa-Piyu campus support.'
              : 'Your ASKa-Piyu account details.',
          style: const TextStyle(
            color: DesignTokens.muted,
            fontSize: 14,
            height: 1.4,
          ),
        ),
        const SizedBox(height: 28),
        _AccountGroup(
          children: [
            _AccountValueRow(label: 'Name', value: user.fullName),
            _AccountValueRow(label: 'Email', value: user.email),
            _AccountValueRow(
              label: 'Role',
              value: SettingsPage.roleLabel(user.role),
              isLast: office.isEmpty,
            ),
            if (office.isNotEmpty)
              _AccountValueRow(
                label: isFaculty ? 'College / office' : 'Office',
                value: office,
                isLast: true,
              ),
          ],
        ),
        const SizedBox(height: 14),
        _AccountGroup(
          children: [
            _AccountActionRow(
              label: 'Change password',
              trailing: const Icon(
                Icons.chevron_right_rounded,
                color: DesignTokens.muted,
              ),
              onTap: onChangePassword,
            ),
            _AccountValueRow(
              label: 'Email verification',
              value: user.emailVerified ? 'Verified' : 'Pending',
              valueColor: user.emailVerified
                  ? const Color(0xFF15803D)
                  : const Color(0xFFB45309),
              isLast: true,
            ),
          ],
        ),
        const SizedBox(height: 14),
        _AccountGroup(
          children: [
            _AccountActionRow(
              label: 'Sign out',
              trailing: const Icon(
                Icons.logout_rounded,
                size: 18,
                color: Color(0xFFB91C1C),
              ),
              labelColor: const Color(0xFFB91C1C),
              isLast: true,
              onTap: () => onSignOut(),
            ),
          ],
        ),
      ],
    );
  }
}

class _AccountGroup extends StatelessWidget {
  final List<Widget> children;

  const _AccountGroup({required this.children});

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: BoxDecoration(
        color: const Color(0xFFF8FAFC),
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: DesignTokens.border),
      ),
      clipBehavior: Clip.antiAlias,
      child: Column(children: children),
    );
  }
}

class _AccountValueRow extends StatelessWidget {
  final String label;
  final String value;
  final Color? valueColor;
  final bool isLast;

  const _AccountValueRow({
    required this.label,
    required this.value,
    this.valueColor,
    this.isLast = false,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 16),
      decoration: BoxDecoration(
        border: isLast
            ? null
            : const Border(bottom: BorderSide(color: DesignTokens.border)),
      ),
      child: Row(
        children: [
          Expanded(
            child: Text(
              label,
              style: const TextStyle(
                color: DesignTokens.ink,
                fontWeight: FontWeight.w600,
                fontSize: 14,
              ),
            ),
          ),
          Flexible(
            child: Text(
              value,
              textAlign: TextAlign.right,
              style: TextStyle(
                color: valueColor ?? DesignTokens.muted,
                fontWeight: FontWeight.w600,
                fontSize: 14,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _AccountActionRow extends StatelessWidget {
  final String label;
  final Widget trailing;
  final VoidCallback onTap;
  final Color? labelColor;
  final bool isLast;

  const _AccountActionRow({
    required this.label,
    required this.trailing,
    required this.onTap,
    this.labelColor,
    this.isLast = false,
  });

  @override
  Widget build(BuildContext context) {
    return Material(
      color: Colors.transparent,
      child: InkWell(
        onTap: onTap,
        child: Container(
          width: double.infinity,
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 16),
          decoration: BoxDecoration(
            border: isLast
                ? null
                : const Border(bottom: BorderSide(color: DesignTokens.border)),
          ),
          child: Row(
            children: [
              Expanded(
                child: Text(
                  label,
                  style: TextStyle(
                    color: labelColor ?? DesignTokens.ink,
                    fontWeight: FontWeight.w600,
                    fontSize: 14,
                  ),
                ),
              ),
              trailing,
            ],
          ),
        ),
      ),
    );
  }
}

class _SettingsSignedOut extends StatelessWidget {
  const _SettingsSignedOut();

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(28),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(18),
        border: Border.all(color: DesignTokens.border),
      ),
      child: const Text(
        'Log in to manage your account settings.',
        style: TextStyle(color: DesignTokens.muted, height: 1.45),
      ),
    );
  }
}

class _ChangePasswordDialog extends StatefulWidget {
  const _ChangePasswordDialog();

  @override
  State<_ChangePasswordDialog> createState() => _ChangePasswordDialogState();
}

class _ChangePasswordDialogState extends State<_ChangePasswordDialog> {
  final _formKey = GlobalKey<FormState>();
  final _currentCtrl = TextEditingController();
  final _newCtrl = TextEditingController();
  final _confirmCtrl = TextEditingController();
  bool _loading = false;
  bool _obscureCurrent = true;
  bool _obscureNew = true;
  bool _obscureConfirm = true;
  String? _error;

  @override
  void dispose() {
    _currentCtrl.dispose();
    _newCtrl.dispose();
    _confirmCtrl.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (!(_formKey.currentState?.validate() ?? false)) return;
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      await AuthScope.of(context).changePassword(
        ChangePasswordRequest(
          currentPassword: _currentCtrl.text,
          newPassword: _newCtrl.text,
        ),
      );
      if (!mounted) return;
      Navigator.of(context).pop(true);
    } catch (error) {
      if (!mounted) return;
      setState(() => _error = _friendlyError(error));
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  String _friendlyError(Object error) {
    final text = error.toString().replaceFirst('Bad state: ', '').trim();
    if (text.isEmpty) return 'Could not change password.';
    return text;
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('Change password'),
      content: SizedBox(
        width: 360,
        child: Form(
          key: _formKey,
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              TextFormField(
                controller: _currentCtrl,
                obscureText: _obscureCurrent,
                enabled: !_loading,
                decoration: InputDecoration(
                  labelText: 'Current password',
                  suffixIcon: IconButton(
                    onPressed: () =>
                        setState(() => _obscureCurrent = !_obscureCurrent),
                    icon: Icon(
                      _obscureCurrent
                          ? Icons.visibility_outlined
                          : Icons.visibility_off_outlined,
                    ),
                  ),
                ),
                validator: (value) {
                  if ((value ?? '').isEmpty) {
                    return 'Enter your current password.';
                  }
                  return null;
                },
              ),
              const SizedBox(height: 12),
              TextFormField(
                controller: _newCtrl,
                obscureText: _obscureNew,
                enabled: !_loading,
                decoration: InputDecoration(
                  labelText: 'New password',
                  helperText:
                      'At least 10 characters, with a letter and a number.',
                  suffixIcon: IconButton(
                    onPressed: () => setState(() => _obscureNew = !_obscureNew),
                    icon: Icon(
                      _obscureNew
                          ? Icons.visibility_outlined
                          : Icons.visibility_off_outlined,
                    ),
                  ),
                ),
                validator: (value) {
                  final text = value ?? '';
                  if (text.isEmpty) return 'Enter a new password.';
                  if (text.length < 10) return 'Use at least 10 characters.';
                  if (!RegExp(r'[A-Za-z]').hasMatch(text)) {
                    return 'Include at least one letter.';
                  }
                  if (!RegExp(r'\d').hasMatch(text)) {
                    return 'Include at least one number.';
                  }
                  if (text == _currentCtrl.text) {
                    return 'New password must differ from the current one.';
                  }
                  return null;
                },
              ),
              const SizedBox(height: 12),
              TextFormField(
                controller: _confirmCtrl,
                obscureText: _obscureConfirm,
                enabled: !_loading,
                decoration: InputDecoration(
                  labelText: 'Confirm new password',
                  suffixIcon: IconButton(
                    onPressed: () =>
                        setState(() => _obscureConfirm = !_obscureConfirm),
                    icon: Icon(
                      _obscureConfirm
                          ? Icons.visibility_outlined
                          : Icons.visibility_off_outlined,
                    ),
                  ),
                ),
                validator: (value) {
                  if (value != _newCtrl.text) return 'Passwords do not match.';
                  return null;
                },
              ),
              if (_error != null) ...[
                const SizedBox(height: 12),
                Align(
                  alignment: Alignment.centerLeft,
                  child: Text(
                    _error!,
                    style: const TextStyle(color: Colors.red, fontSize: 13),
                  ),
                ),
              ],
            ],
          ),
        ),
      ),
      actions: [
        TextButton(
          onPressed: _loading ? null : () => Navigator.of(context).pop(false),
          child: const Text('Cancel'),
        ),
        FilledButton(
          onPressed: _loading ? null : _submit,
          child: _loading
              ? const SizedBox(
                  width: 18,
                  height: 18,
                  child: CircularProgressIndicator(strokeWidth: 2),
                )
              : const Text('Update password'),
        ),
      ],
    );
  }
}
