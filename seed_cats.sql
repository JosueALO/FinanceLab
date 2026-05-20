DELETE FROM categoria_arbol;
DELETE FROM macro_categorias;

INSERT INTO macro_categorias (nombre, icono) VALUES
('Despensa', '🛒'),
('Comida Fuera', '🍽️'),
('Vivienda', '🏠'),
('Transporte', '🚗'),
('Salud y Mascotas', '💊'),
('Entretenimiento', '🎬'),
('Hogar y Ropa', '🛋️'),
('Finanzas', '💰'),
('Social', '🎁'),
('Digital', '💻'),
('Otros', '📦');

-- Mapeo macro → categorías
INSERT INTO categoria_arbol (tipo_operacion_id, macro, nombre) VALUES
(1, 'Despensa', 'Alimentación y Despensa'),
(1, 'Despensa', 'Gusguería'),
(1, 'Comida Fuera', 'Restaurantes y Cafeterías'),
(1, 'Vivienda', 'Vivienda y Servicios (Renta, Luz, Agua)'),
(1, 'Transporte', 'Transporte (Gasolina, Uber, Mto)'),
(1, 'Salud y Mascotas', 'Salud y Cuidado Personal'),
(1, 'Salud y Mascotas', 'Mascotas (Gatos)'),
(1, 'Entretenimiento', 'Entretenimiento y Ocio'),
(1, 'Entretenimiento', 'Vacaciones'),
(1, 'Hogar y Ropa', 'Muebles y Hogar'),
(1, 'Hogar y Ropa', 'Ropa y Calzado'),
(1, 'Finanzas', 'Ahorro e Inversión'),
(1, 'Social', 'Regalos (Familia, Amigos)'),
(1, 'Digital', 'Suscripciones y Tecnología'),
(1, 'Otros', 'Otro'),
(2, 'General', 'Ingreso')
ON CONFLICT DO NOTHING;
