import 'package:flutter/material.dart';

import '../auth/auth_navigation.dart';
import '../auth/auth_state.dart';
import '../models/auth_models.dart';
import '../navigation/soft_page_route.dart';
import '../services/local_store.dart';
import '../widgets/auth_split_shell.dart';
import 'signup_page.dart';

class LoginPage extends StatefulWidget {
  static const routeName = '/login';

  final WidgetBuilder? returnTo;
  final String? message;

  /// When set, [returnTo] is honored only if the logged-in role matches.
  final String? gateRole;

  const LoginPage({super.key, this.returnTo, this.message, this.gateRole});

  @override
  State<LoginPage> createState() => _LoginPageState();
}

class _LoginPageState extends State<LoginPage> {
  final _formKey = GlobalKey<FormState>();
  final _emailCtrl = TextEditingController();
  final _passwordCtrl = TextEditingController();
  bool _loading = false;
  bool _rememberMe = false;
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
      final user = await AuthScope.of(context).login(
        LoginRequest(
          email: _emailCtrl.text,
          password: _passwordCtrl.text,
          rememberMe: _rememberMe,
        ),
        rememberMe: _rememberMe,
      );
      await LocalStore.setRememberMePreference(_rememberMe);
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

  void _openSignup() {
    softReplace(
      context,
      SignupPage(
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
              'Sign In',
              style: TextStyle(
                fontSize: 32,
                fontWeight: FontWeight.w800,
                color: AuthSplitShell.maroon,
              ),
            ),
            const SizedBox(height: 8),
            const Text(
              'Access your ASKa-Piyu account to continue using '
              'student services.',
              style: TextStyle(
                color: Color(0xFF6B7280),
                height: 1.4,
                fontSize: 14,
              ),
            ),
            if (widget.message != null) ...[
              const SizedBox(height: 10),
              Text(
                widget.message!,
                style: const TextStyle(color: Color(0xFF6B7280), height: 1.4),
              ),
            ],
            const SizedBox(height: 26),
            AuthLabeledField(
              label: 'Email',
              field: TextFormField(
                controller: _emailCtrl,
                keyboardType: TextInputType.emailAddress,
                textInputAction: TextInputAction.next,
                validator: _validateEmail,
                decoration: authFieldDecoration('Enter your email'),
              ),
            ),
            const SizedBox(height: 14),
            AuthLabeledField(
              label: 'Password',
              field: TextFormField(
                controller: _passwordCtrl,
                obscureText: _obscurePassword,
                onFieldSubmitted: (_) => _submit(),
                validator:
                    (value) =>
                        (value == null || value.isEmpty)
                            ? 'Enter your password.'
                            : null,
                decoration: authFieldDecoration('Enter your password').copyWith(
                  suffixIcon: IconButton(
                    onPressed:
                        () => setState(
                          () => _obscurePassword = !_obscurePassword,
                        ),
                    icon: Icon(
                      _obscurePassword
                          ? Icons.visibility_outlined
                          : Icons.visibility_off_outlined,
                      color: const Color(0xFF9CA3AF),
                    ),
                  ),
                ),
              ),
            ),
            const SizedBox(height: 12),
            // Expanded (not a bare Spacer) between the label and the
            // button: it still pushes "Forgot password?" to the row's far
            // right like the old Spacer-based layout did, but its child
            // can shrink with an ellipsis instead of forcing overflow --
            // at ~390px the previous fixed-width Text + Spacer combination
            // overflowed the form column by ~73px.
            Row(
              children: [
                SizedBox(
                  width: 22,
                  height: 22,
                  child: Checkbox(
                    value: _rememberMe,
                    onChanged:
                        (value) => setState(() => _rememberMe = value ?? false),
                    activeColor: AuthSplitShell.maroon,
                    side: const BorderSide(color: AuthSplitShell.maroon),
                    materialTapTargetSize: MaterialTapTargetSize.shrinkWrap,
                  ),
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: const Text(
                    'Remember me!',
                    overflow: TextOverflow.ellipsis,
                    style: TextStyle(
                      color: AuthSplitShell.maroon,
                      fontWeight: FontWeight.w600,
                      fontSize: 13,
                    ),
                  ),
                ),
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
                    overflow: TextOverflow.ellipsis,
                    style: TextStyle(fontWeight: FontWeight.w600, fontSize: 13),
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
              label: 'Login',
              loading: _loading,
              onPressed: _submit,
            ),
            const SizedBox(height: 22),
            const AuthOrDivider(text: "Don't have an account?"),
            const SizedBox(height: 18),
            AuthSecondaryButton(
              label: 'Sign Up',
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
