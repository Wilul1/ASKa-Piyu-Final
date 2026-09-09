import 'package:flutter/material.dart';

import '../auth/auth_navigation.dart';
import '../auth/auth_state.dart';
import '../models/auth_models.dart';
import '../navigation/soft_page_route.dart';
import '../widgets/auth_split_shell.dart';
import 'login_page.dart';

class SignupPage extends StatefulWidget {
  final WidgetBuilder? returnTo;
  final String? message;
  final String? gateRole;

  const SignupPage({
    super.key,
    this.returnTo,
    this.message,
    this.gateRole,
  });

  @override
  State<SignupPage> createState() => _SignupPageState();
}

class _SignupPageState extends State<SignupPage> {
  final _formKey = GlobalKey<FormState>();
  final _nameCtrl = TextEditingController();
  final _emailCtrl = TextEditingController();
  final _passwordCtrl = TextEditingController();
  final _confirmCtrl = TextEditingController();
  bool _loading = false;
  bool _obscurePassword = true;
  bool _obscureConfirm = true;
  String? _error;

  @override
  void dispose() {
    _nameCtrl.dispose();
    _emailCtrl.dispose();
    _passwordCtrl.dispose();
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
      final user = await AuthScope.of(context).signup(SignupRequest(
        fullName: _nameCtrl.text,
        email: _emailCtrl.text,
        password: _passwordCtrl.text,
        role: 'student',
      ));
      if (!mounted) return;
      redirectAfterAuth(
        context,
        user.role,
        widget.returnTo,
        gateRole: widget.gateRole,
        emailVerified: user.emailVerified,
      );
    } catch (error) {
      if (!mounted) return;
      setState(() => _error = _friendlyError(error));
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  void _openLogin() {
    softReplace(
      context,
      LoginPage(
        returnTo: widget.returnTo,
        message: widget.message,
        gateRole: widget.gateRole,
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return AuthSplitShell(
      form: Form(
        key: _formKey,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            const Text(
              'SIGN UP',
              style: TextStyle(
                fontSize: 26,
                fontWeight: FontWeight.w900,
                color: AuthSplitShell.maroon,
                letterSpacing: 1.0,
              ),
            ),
            const SizedBox(height: 8),
            const Text(
              'Use your real email (like Gmail). We will send a 6-digit code to verify it before you can submit tickets. Create a password for ASKa-Piyu only — not your email password.',
              style: TextStyle(
                color: Color(0xFF6B7280),
                height: 1.4,
                fontSize: 13,
              ),
            ),
            if (widget.message != null) ...[
              const SizedBox(height: 10),
              Text(
                widget.message!,
                style: const TextStyle(
                  color: Color(0xFF6B7280),
                  height: 1.4,
                ),
              ),
            ],
            const SizedBox(height: 22),
            TextFormField(
              controller: _nameCtrl,
              textInputAction: TextInputAction.next,
              validator: (value) => (value == null || value.trim().isEmpty)
                  ? 'Enter your full name.'
                  : null,
              decoration: authFieldDecoration('Full name'),
            ),
            const SizedBox(height: 12),
            TextFormField(
              controller: _emailCtrl,
              keyboardType: TextInputType.emailAddress,
              textInputAction: TextInputAction.next,
              validator: _validateEmail,
              decoration: authFieldDecoration('Email (e.g. your Gmail)'),
            ),
            const SizedBox(height: 12),
            TextFormField(
              controller: _passwordCtrl,
              obscureText: _obscurePassword,
              textInputAction: TextInputAction.next,
              validator: (value) {
                final text = value ?? '';
                if (text.isEmpty) return 'Enter a password.';
                if (text.length < 10) {
                  return 'Use at least 10 characters.';
                }
                final hasLetter = text.contains(RegExp(r'[A-Za-z]'));
                final hasDigit = text.contains(RegExp(r'\d'));
                if (!hasLetter || !hasDigit) {
                  return 'Include at least one letter and one number.';
                }
                return null;
              },
              decoration: authFieldDecoration('ASKa-Piyu password').copyWith(
                suffixIcon: IconButton(
                  onPressed: () =>
                      setState(() => _obscurePassword = !_obscurePassword),
                  icon: Icon(
                    _obscurePassword
                        ? Icons.visibility_outlined
                        : Icons.visibility_off_outlined,
                    color: const Color(0xFF9CA3AF),
                  ),
                ),
              ),
            ),
            const SizedBox(height: 12),
            TextFormField(
              controller: _confirmCtrl,
              obscureText: _obscureConfirm,
              onFieldSubmitted: (_) => _submit(),
              validator: (value) => value != _passwordCtrl.text
                  ? 'Passwords do not match.'
                  : null,
              decoration: authFieldDecoration('Confirm password').copyWith(
                suffixIcon: IconButton(
                  onPressed: () =>
                      setState(() => _obscureConfirm = !_obscureConfirm),
                  icon: Icon(
                    _obscureConfirm
                        ? Icons.visibility_outlined
                        : Icons.visibility_off_outlined,
                    color: const Color(0xFF9CA3AF),
                  ),
                ),
              ),
            ),
            if (_error != null) ...[
              const SizedBox(height: 14),
              AuthErrorBanner(message: _error!),
            ],
            const SizedBox(height: 20),
            AuthPrimaryButton(
              label: 'SIGN UP',
              loading: _loading,
              onPressed: _submit,
            ),
            const SizedBox(height: 20),
            const AuthOrDivider(text: 'Already have an account?'),
            const SizedBox(height: 16),
            AuthSecondaryButton(
              label: 'LOGIN',
              onPressed: _loading ? null : _openLogin,
            ),
          ],
        ),
      ),
    );
  }
}

String? _validateEmail(String? value) {
  final text = value?.trim() ?? '';
  if (text.isEmpty) return 'Enter your email address.';
  if (!text.contains('@') || !text.split('@').last.contains('.')) {
    return 'Enter a valid email address.';
  }
  return null;
}

String _friendlyError(Object error) {
  final text = error.toString().replaceFirst('Bad state: ', '').trim();
  return text.isEmpty ? 'Something went wrong. Please try again.' : text;
}
