// frontend/src/features/cart/context/CartContext.jsx
import { createContext, useContext, useState, useEffect } from 'react';
import { apiFetch } from '../../../lib/api';
import { useAuth } from '../../auth/context/AuthContext'; // Importamos Auth

const CartContext = createContext();

export const CartProvider = ({ children }) => {
  const [cart, setCart] = useState(null); // Guardará el carrito completo
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const { isAuthenticated, user } = useAuth(); // Leemos el estado de autenticación

  // Efecto para cargar el carrito cuando el usuario se autentica
  useEffect(() => {
    const fetchCart = async () => {
      // Solo buscamos el carrito si el usuario está logueado Y verificado
      if (isAuthenticated && user?.age_verified) {
        setLoading(true);
        try {
          //
          const data = await apiFetch('/cart/'); 
          setCart(data);
        } catch (err) {
          setError(err.message);
        } finally {
          setLoading(false);
        }
      } else {
        // Si no está logueado o verificado, el carrito es null
        setCart(null);
        setLoading(false);
      }
    };

    fetchCart();
  }, [isAuthenticated, user]); // Se re-ejecuta si el usuario cambia

  // --- Funciones para interactuar con el carrito ---

  const addToCart = async (productId, quantity) => {
    if (!isAuthenticated || !user?.age_verified) {
      throw new Error("Debes estar logueado y verificado para comprar.");
    }

    try {
      //
      const updatedCart = await apiFetch('/cart/add', {
        method: 'POST',
        body: { product_id: productId, quantity: quantity }
      });
      setCart(updatedCart); // Actualizamos el estado global
    } catch (err) {
      console.error("Error al añadir al carrito:", err);
      throw err;
    }
  };

  // --- ¡NUEVA FUNCIÓN! ---
  const updateQuantity = async (productId, newQuantity) => {
    if (newQuantity <= 0) {
      // Si la cantidad es 0 o menos, eliminamos el item
      await removeFromCart(productId);
      return;
    }
    try {
      //
      const updatedCart = await apiFetch('/cart/update', {
        method: 'PUT',
        body: { product_id: productId, quantity: newQuantity }
      });
      setCart(updatedCart);
    } catch (err) {
      console.error("Error al actualizar cantidad:", err);
      throw err;
    }
  };

  // --- ¡NUEVA FUNCIÓN! ---
  const removeFromCart = async (productId) => {
    try {
      //
      const updatedCart = await apiFetch(`/cart/remove/${productId}`, {
        method: 'DELETE',
      });
      setCart(updatedCart);
    } catch (err) {
      console.error("Error al eliminar item:", err);
      throw err;
    }
  };
  
  // --- ¡NUEVA FUNCIÓN! ---
  const clearCart = async () => {
    try {
      //
      const updatedCart = await apiFetch('/cart/clear', {
        method: 'DELETE',
      });
      setCart(updatedCart);
    } catch (err) {
      console.error("Error al vaciar el carrito:", err);
      throw err;
    }
  };

  const value = {
    cart,
    loading,
    error,
    addToCart,
    updateQuantity,
    removeFromCart,
    clearCart,
  };

  return <CartContext.Provider value={value}>{children}</CartContext.Provider>;
};

// Hook para consumir el contexto
export const useCart = () => {
  const context = useContext(CartContext);
  if (context === undefined) {
    throw new Error("useCart debe ser usado dentro de un CartProvider");
  }
  return context;
};