import 'package:flutter/material.dart';

import '../auth/auth_navigation.dart';
import '../auth/auth_state.dart';
import '../design_tokens.dart';
import '../models/auth_models.dart';
import '../widgets/student_ui.dart';
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
        builder: (_) => SignupPage(returnTo: widget.returnTo, message: widget.message),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: DesignTokens.bgGrey,
      appBar: AppBar(title: const Text('Login')),
      body: StudentPage(
        maxWidth: 520,
        child: StudentPanel(
          padding: const EdgeInsets.all(24),
          child: Form(
            key: _formKey,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                const StudentIconBox(
                  icon: Icons.lock_person_rounded,
                  color: DesignTokens.maroon,
                  size: 52,
                ),
                const SizedBox(height: 18),
                const Text(
                  'Log in to ASKa-Piyu',
                  style: TextStyle(
                    fontSize: 26,
                    fontWeight: FontWeight.w900,
                    color: DesignTokens.ink,
                  ),
                ),
                if (widget.message != null) ...[
                  const SizedBox(height: 10),
                  Text(
                    widget.message!,
                    style: const TextStyle(
                      color: DesignTokens.muted,
                      height: 1.4,
                    ),
                  ),
                ],
                const SizedBox(height: 22),
                TextFormField(
                  controller: _emailCtrl,
                  keyboardType: TextInputType.emailAddress,
                  textInputAction: TextInputAction.next,
                  validator: _validateEmail,
                  decoration: _authDecoration(
                    label: 'Email',
                    icon: Icons.alternate_email_rounded,
                  ),
                ),
                const SizedBox(height: 14),
                TextFormField(
                  controller: _passwordCtrl,
                  obscureText: true,
                  onFieldSubmitted: (_) => _submit(),
                  validator: (value) =>
                      (value == null || value.isEmpty) ? 'Enter your password.' : null,
                  decoration: _authDecoration(
                    label: 'Password',
                    icon: Icons.password_rounded,
                  ),
                ),
                if (_error != null) ...[
                  const SizedBox(height: 14),
                  _ErrorBanner(message: _error!),
                ],
                const SizedBox(height: 22),
                ElevatedButton(
                  onPressed: _loading ? null : _submit,
                  style: ElevatedButton.styleFrom(
                    backgroundColor: DesignTokens.maroon,
                    foregroundColor: Colors.white,
                    elevation: 0,
                    padding: const EdgeInsets.symmetric(vertical: 15),
                    shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(14),
                    ),
                  ),
                  child: _loading
                      ? const SizedBox(
                          width: 18,
                          height: 18,
                          child: CircularProgressIndicator(
                            strokeWidth: 2,
                            color: Colors.white,
                          ),
                        )
                      : Text(_loading ? 'Logging in...' : 'Login'),
                ),
                const SizedBox(height: 12),
                TextButton(
                  onPressed: _loading ? null : _openSignup,
                  child: const Text('Create a student account'),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _ErrorBanner extends StatelessWidget {
  final String message;

  const _ErrorBanner({required this.message});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: const Color(0xFFFFF7ED),
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: const Color(0xFFFED7AA)),
      ),
      child: Row(
        children: [
          const Icon(Icons.error_outline_rounded, color: Color(0xFFC2410C)),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              message,
              style: const TextStyle(color: Color(0xFF9A3412), height: 1.35),
            ),
          ),
        ],
      ),
    );
  }
}

InputDecoration _authDecoration({required String label, required IconData icon}) {
  return InputDecoration(
    labelText: label,
    filled: true,
    fillColor: const Color(0xFFF8FAFC),
    prefixIcon: Icon(icon, size: 20),
    border: OutlineInputBorder(
      borderRadius: BorderRadius.circular(14),
      borderSide: const BorderSide(color: DesignTokens.border),
    ),
    enabledBorder: OutlineInputBorder(
      borderRadius: BorderRadius.circular(14),
      borderSide: const BorderSide(color: DesignTokens.border),
    ),
    focusedBorder: OutlineInputBorder(
      borderRadius: BorderRadius.circular(14),
      borderSide: const BorderSide(color: DesignTokens.maroon, width: 1.4),
    ),
  );
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
