// frontend/src/features/checkout/pages/CheckoutPage.jsx
import { useState } from 'react';
import { useCart } from '../../cart/context/CartContext';
import { apiFetch } from '../../../lib/api';
import { AddressForm } from "../components/AddressForm.jsx";

export const CheckoutPage = () => {
  const { cart, clearCart } = useCart(); // Necesitamos el carrito y la función de limpiar
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState(null);

  // Esta función se activará desde el AddressForm
  const handleCheckoutSubmit = async (addressData) => {
    setIsSubmitting(true);
    setError(null);

    if (!cart || cart.items.length === 0) {
      setError("Tu carrito está vacío. No puedes proceder al pago.");
      setIsSubmitting(false);
      return;
    }

    try {
      // --- PASO 1: CREAR LA ORDEN ---
      // El body debe coincidir con el modelo OrderCreate
      const orderBody = {
        items: cart.items, // Pasamos los items del carrito (product_id, quantity)
        shipping_address: addressData // Pasamos la dirección del formulario
      };

      //
      const newOrder = await apiFetch('/orders/', {
        method: 'POST',
        body: orderBody,
      });

      // --- PASO 2: CREAR PREFERENCIA DE PAGO ---
      if (!newOrder || !newOrder.id) {
        throw new Error("No se pudo crear la orden.");
      }

      //
      const preference = await apiFetch(`/payments/create-preference/${newOrder.id}`, {
        method: 'POST',
      });

      // --- PASO 3: LIMPIAR CARRITO Y REDIRIGIR A MERCADO PAGO ---
      if (preference && preference.init_point) {
        clearCart(); // Vaciamos el carrito local

        // Redirigimos al usuario a la URL de Mercado Pago
        window.location.href = preference.init_point;
      } else {
        throw new Error("No se pudo obtener el link de pago.");
      }

    } catch (err) {
      console.error("Error en el checkout:", err);
      setError(err.message || "Ocurrió un error al procesar tu pedido.");
      setIsSubmitting(false);
    }
  };

  return (
    <div className="container mx-auto p-4 max-w-2xl">
      <h1 className="text-3xl font-bold text-center mb-8 text-gray-800">
        Finalizar Compra
      </h1>

      {error && (
        <div className="bg-red-100 border border-red-400 text-red-700 px-4 py-3 rounded mb-4">
          {error}
        </div>
      )}

      <AddressForm 
        onSubmit={handleCheckoutSubmit} 
        isSubmitting={isSubmitting} 
      />
    </div>
  );
};