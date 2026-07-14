import java.util.AbstractList;
import java.util.Arrays;


// A fixed-capacity list that exposes the oldest item at index 0.
// Once full, push() overwrites the oldest item in O(1) time.
public class FixedStack<T> extends AbstractList<T> {
    private Object[] elements;
    private int maxSize;
    private int start;
    private int count;

    public FixedStack(int size) {
        setSize(size);
    }

    public FixedStack() {
        setSize(1000);
    }

    public void setSize(int size) {
        if (size < 0) {
            throw new IllegalArgumentException("FixedStack size cannot be negative");
        }
        maxSize = size;
        elements = new Object[maxSize];
        start = 0;
        count = 0;
        modCount++;
    }

    public void fill(T object) {
        Arrays.fill(elements, object);
        start = 0;
        count = maxSize;
        modCount++;
    }

    public T push(T object) {
        if (maxSize == 0) {
            return object;
        }

        if (count < maxSize) {
            elements[(start + count) % maxSize] = object;
            count++;
        } else {
            elements[start] = object;
            start = (start + 1) % maxSize;
        }
        modCount++;
        return object;
    }

    @Override
    public T get(int index) {
        if (index < 0 || index >= count) {
            throw new IndexOutOfBoundsException("index=" + index + ", size=" + count);
        }
        @SuppressWarnings("unchecked")
        T value = (T)elements[(start + index) % maxSize];
        return value;
    }

    @Override
    public int size() {
        return count;
    }
}
