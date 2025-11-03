import { LoginForm } from '../components/LoginForm';

export const LoginPage = () => {
  return (
    <div>
      <h1 className="text-3xl font-bold text-center mb-8 text-gray-800">
        Iniciar Sesión
      </h1>
      <LoginForm />
    </div>
  );
};