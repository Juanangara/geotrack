-- Sample data around Bogota. Points are (longitude, latitude).
INSERT INTO couriers (name, status) VALUES
    ('Ana', 'available'),
    ('Luis', 'available'),
    ('Marta', 'busy');

INSERT INTO courier_positions (courier_id, position) VALUES
    (1, ST_MakePoint(-74.0721, 4.7110)::geography),
    (2, ST_MakePoint(-74.0445, 4.6697)::geography),
    (3, ST_MakePoint(-74.1000, 4.6000)::geography);

INSERT INTO orders (destination) VALUES
    (ST_MakePoint(-74.0600, 4.6900)::geography),
    (ST_MakePoint(-74.0800, 4.6500)::geography);
