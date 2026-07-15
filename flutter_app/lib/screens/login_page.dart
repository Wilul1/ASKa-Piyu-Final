import 'package:flutter/material.dart';

import '../auth/auth_navigation.dart';
import '../auth/auth_state.dart';
import '../models/auth_models.dart';
import '../widgets/auth_split_shell.dart';
import 'signup_page.dart';

class LoginPage extends StatefulWidget {
  final WidgetBuilder? returnTo;
  final String? message;

  const LoginPage({super.key, this.returnTo, this.message});

  @override
  State<LoginPage> createState() => _LoginPageState();
}

class _LoginPageState extends State<LoginPage> {
  final _formKey = GlobalKey<FormState>();
  final _emailCtrl = TextEditingController();
  final _passwordCtrl = TextEditingController();
  bool _loading = false;
  bool _rememberMe = true;
  bool _obscurePassword = true;
  String? _error;

  @override
  void dispose() {
    _emailCtrl.dispose();
    _passwordCtrl.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (!(_formKey.currentState?.validate() ?? false)) return;
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final user = await AuthScope.of(context).login(LoginRequest(
        email: _emailCtrl.text,
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

  void _openSignup() {
    Navigator.of(context).pushReplacement(
      MaterialPageRoute(
        builder: (_) =>
            SignupPage(returnTo: widget.returnTo, message: widget.message),
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
              'SIGN IN',
              style: TextStyle(
                fontSize: 28,
                fontWeight: FontWeight.w900,
                color: AuthSplitShell.maroon,
                letterSpacing: 1.2,
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
            const SizedBox(height: 28),
            TextFormField(
              controller: _emailCtrl,
              keyboardType: TextInputType.emailAddress,
              textInputAction: TextInputAction.next,
              validator: _validateEmail,
              decoration: authFieldDecoration('Email'),
            ),
            const SizedBox(height: 14),
            TextFormField(
              controller: _passwordCtrl,
              obscureText: _obscurePassword,
              onFieldSubmitted: (_) => _submit(),
              validator: (value) => (value == null || value.isEmpty)
                  ? 'Enter your password.'
                  : null,
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
            Row(
              children: [
                SizedBox(
                  width: 22,
                  height: 22,
                  child: Checkbox(
                    value: _rememberMe,
                    onChanged: (value) =>
                        setState(() => _rememberMe = value ?? false),
                    activeColor: AuthSplitShell.maroon,
                    side: const BorderSide(color: AuthSplitShell.maroon),
                    materialTapTargetSize: MaterialTapTargetSize.shrinkWrap,
                  ),
                ),
                const SizedBox(width: 8),
                const Text(
                  'Remember me!',
                  style: TextStyle(
                    color: AuthSplitShell.maroon,
                    fontWeight: FontWeight.w600,
                    fontSize: 13,
                  ),
                ),
                const Spacer(),
                TextButton(
                  onPressed: () {
                    ScaffoldMessenger.of(context).showSnackBar(
                      const SnackBar(
                        content: Text(
                          'Contact ICT or your campus admin to reset your password.',
                        ),
                      ),
                    );
                  },
                  style: TextButton.styleFrom(
                    foregroundColor: AuthSplitShell.maroon,
                    padding: EdgeInsets.zero,
                    minimumSize: Size.zero,
                    tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                  ),
                  child: const Text(
                    'Forgot password?',
                    style: TextStyle(
                      fontWeight: FontWeight.w600,
                      fontSize: 13,
                    ),
                  ),
                ),
              ],
            ),
            if (_error != null) ...[
              const SizedBox(height: 14),
              AuthErrorBanner(message: _error!),
            ],
            const SizedBox(height: 22),
            AuthPrimaryButton(
              label: 'LOGIN',
              loading: _loading,
              onPressed: _submit,
            ),
            const SizedBox(height: 22),
            const AuthOrDivider(text: "Don't have an account?"),
            const SizedBox(height: 18),
            AuthSecondaryButton(
              label: 'CREATE ACCOUNT',
              onPressed: _loading ? null : _openSignup,
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
