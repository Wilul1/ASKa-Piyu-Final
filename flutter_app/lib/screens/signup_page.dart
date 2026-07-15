import 'package:flutter/material.dart';

import '../auth/auth_navigation.dart';
import '../auth/auth_state.dart';
import '../models/auth_models.dart';
import '../widgets/auth_split_shell.dart';
import 'login_page.dart';

class SignupPage extends StatefulWidget {
  final WidgetBuilder? returnTo;
  final String? message;

  const SignupPage({super.key, this.returnTo, this.message});

  @override
  State<SignupPage> createState() => _SignupPageState();
}

class _SignupPageState extends State<SignupPage> {
  final _formKey = GlobalKey<FormState>();
  final _nameCtrl = TextEditingController();
  final _emailCtrl = TextEditingController();
  final _studentIdCtrl = TextEditingController();
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
    _studentIdCtrl.dispose();
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
        studentId: _studentIdCtrl.text,
        password: _passwordCtrl.text,
      ));
      if (!mounted) return;
      redirectAfterAuth(context, user.role, widget.returnTo);
    } catch (error) {
      if (!mounted) return;
      setState(() => _error = _friendlyError(error));
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  void _openLogin() {
    Navigator.of(context).pushReplacement(
      MaterialPageRoute(
        builder: (_) =>
            LoginPage(returnTo: widget.returnTo, message: widget.message),
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
              'CREATE ACCOUNT',
              style: TextStyle(
                fontSize: 26,
                fontWeight: FontWeight.w900,
                color: AuthSplitShell.maroon,
                letterSpacing: 1.0,
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
              decoration: authFieldDecoration('Email'),
            ),
            const SizedBox(height: 12),
            TextFormField(
              controller: _studentIdCtrl,
              textInputAction: TextInputAction.next,
              validator: (value) => (value == null || value.trim().isEmpty)
                  ? 'Enter your student ID.'
                  : null,
              decoration: authFieldDecoration('Student ID'),
            ),
            const SizedBox(height: 12),
            TextFormField(
              controller: _passwordCtrl,
              obscureText: _obscurePassword,
              textInputAction: TextInputAction.next,
              validator: (value) {
                final text = value ?? '';
                if (text.isEmpty) return 'Enter a password.';
                if (text.length < 8) return 'Use at least 8 characters.';
                return null;
              },
              decoration: authFieldDecoration('Password').copyWith(
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
              label: 'CREATE ACCOUNT',
              loading: _loading,
              onPressed: _submit,
            ),
            const SizedBox(height: 20),
            const AuthOrDivider(text: 'Already have an account?'),
            const SizedBox(height: 16),
            AuthSecondaryButton(
              label: 'SIGN IN',
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
